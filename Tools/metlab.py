#!/usr/bin/env python3
# v1.0.0
# Metlab 配布パッケージの管理ツール。
# 開発プロジェクトのツールを配布用リポジトリ（Metlab-AVA / Metlab-WLD）へ同期し、
# VPM 用の ZIP を作って GitHub Release と配信リスト（index.json）へ公開する。
#
# 使い方（vpm-repo のルートで実行）:
#   python Tools/metlab.py sync <パッケージID|all>       開発プロジェクト → 配布用リポジトリへコピー・書き換え
#   python Tools/metlab.py readme                        各リポジトリの README とページを作り直す
#   python Tools/metlab.py build <パッケージID>          ZIP を Dist/ に作る（確認用）
#   python Tools/metlab.py release <パッケージID> <バージョン> "<更新内容>"
#                                                        バージョン更新・コミット・タグ・push・Release・配信リスト更新
#
# 配布用の GUID は「パッケージID＋相対パス」から決まる固定値なので、何度同期しても変わらない。

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

HUB_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = HUB_ROOT / "Tools" / "packages.json"
LISTING_PATH = HUB_ROOT / "index.json"
PAGE_PATH = HUB_ROOT / "index.html"
DIST_DIR = HUB_ROOT / "Dist"

# 配布用パッケージ側で管理し、同期で消さないファイル
KEEP_FILES = {"package.json", "package.json.meta", "CHANGELOG.md", "CHANGELOG.md.meta"}
# GUID の参照を書き換える対象（Unity の YAML / JSON テキスト）
GUID_TEXT_EXTS = {
    ".asset", ".prefab", ".mat", ".controller", ".anim", ".asmdef", ".asmref", ".unity",
    ".overrideController", ".mask", ".playable", ".physicMaterial", ".terrainlayer",
    ".renderTexture", ".lighting", ".spriteatlas", ".cubemap", ".flare",
}
# 文字列置換の対象になりうるテキストファイル
TEXT_EXTS = GUID_TEXT_EXTS | {".cs", ".shader", ".cginc", ".hlsl", ".compute", ".json", ".md", ".txt", ".uss", ".uxml"}

COMMIT_TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"

BOM = b"\xef\xbb\xbf"
GUID_RE = re.compile(r"^guid: ([0-9a-f]{32})\s*$", re.MULTILINE)


# ------------------------------------------------------------------ 共通

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def fail(message: str) -> None:
    print(f"エラー: {message}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        fail(f"コマンド失敗 ({cwd}): {' '.join(cmd)}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def stable_guid(package_id: str, rel_path: str) -> str:
    return hashlib.md5(f"metlab:{package_id}:{rel_path}".encode("utf-8")).hexdigest()


def read_text(path: Path) -> tuple[str, bool]:
    data = path.read_bytes()
    has_bom = data.startswith(BOM)
    return data[len(BOM):].decode("utf-8") if has_bom else data.decode("utf-8"), has_bom


def write_text(path: Path, text: str, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((BOM if bom else b"") + text.encode("utf-8"))


def write_json(path: Path, value: dict) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def package_dir(config: dict, repo_key: str, package_id: str) -> Path:
    return Path(config["repos"][repo_key]["local"]) / "Packages" / package_id


# ------------------------------------------------------------------ .meta

def meta_text(path: Path, guid: str) -> str:
    head = f"fileFormatVersion: 2\nguid: {guid}\n"
    if path.is_dir():
        return head + "folderAsset: yes\nDefaultImporter:\n  externalObjects: {}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
    ext = path.suffix.lower()
    if ext == ".asmdef":
        return head + "AssemblyDefinitionImporter:\n  externalObjects: {}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
    if ext == ".asset":
        return head + "NativeFormatImporter:\n  externalObjects: {}\n  mainObjectFileID: 11400000\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
    if ext == ".cs":
        return head + ("MonoImporter:\n  externalObjects: {}\n  serializedVersion: 2\n  defaultReferences: []\n"
                       "  executionOrder: 0\n  icon: {instanceID: 0}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n")
    return head + "TextScriptImporter:\n  externalObjects: {}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n"


def ensure_metas(package_id: str, root: Path) -> None:
    """メタの無いファイル・フォルダに、固定 GUID のメタを作る（パッケージ直下フォルダ自身は不要）。"""
    for path in sorted(root.rglob("*")):
        if path.suffix == ".meta" or ".git" in path.parts:
            continue
        meta = path.with_name(path.name + ".meta")
        if not meta.exists():
            rel = path.relative_to(root).as_posix()
            write_text(meta, meta_text(path, stable_guid(package_id, rel)))
    # 本体が無いのに残ったメタを消す
    for meta in sorted(root.rglob("*.meta")):
        if not meta.with_name(meta.name[:-5]).exists():
            meta.unlink()


# ------------------------------------------------------------------ sync

def is_excluded(rel: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        for candidate in (rel, rel[:-5] if rel.endswith(".meta") else rel):
            if candidate == pattern or candidate.startswith(pattern + "/") or fnmatch.fnmatch(candidate, pattern):
                return True
    return False


def copy_sources(spec: dict, dest: Path) -> None:
    for source in spec["sources"]:
        src_root = Path(source["from"])
        if not src_root.is_dir():
            fail(f"コピー元が見つかりません: {src_root}")
        target_root = dest / source.get("to", "")
        for path in sorted(src_root.rglob("*")):
            rel = path.relative_to(src_root).as_posix()
            if is_excluded(rel, source.get("exclude", [])):
                continue
            target = target_root / rel
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)


def glob_match(rel: str, pattern: str) -> bool:
    """「**/」は0階層以上として扱う（直下のファイルにも当たる）。"""
    if rel == pattern or fnmatch.fnmatch(rel, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatch(rel, pattern[3:])


def wrap_namespace(text: str, namespace: str) -> tuple[str, int]:
    """名前空間の無いスクリプトを、最初の型宣言（直前の属性を含む）から末尾まで namespace で包む。"""
    if re.search(r"^namespace\s", text, re.MULTILINE):
        return text, 0
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"(public |internal |\[)", line)), None)
    if start is None:
        return text, 0
    body = [("    " + line) if line.strip() else line for line in lines[start:]]
    while body and not body[-1].strip():
        body.pop()
    wrapped = lines[:start] + [f"namespace {namespace}", "{"] + body + ["}", ""]
    return newline.join(wrapped), 1


def apply_replacements(spec: dict, dest: Path) -> None:
    for rule in spec.get("replace", []):
        hits = 0
        for path in sorted(dest.rglob("*")):
            if not path.is_file() or path.suffix == ".meta" or path.suffix.lower() not in TEXT_EXTS:
                continue
            rel = path.relative_to(dest).as_posix()
            if not glob_match(rel, rule["glob"]):
                continue
            text, bom = read_text(path)
            if "wrapNamespace" in rule:
                new_text, count = wrap_namespace(text, rule["wrapNamespace"])
            elif "regex" in rule:
                new_text, count = re.subn(rule["regex"], rule["new"], text)
            else:
                count = text.count(rule["old"])
                new_text = text.replace(rule["old"], rule["new"])
            if count:
                write_text(path, new_text, bom)
                hits += count
        if hits == 0:
            fail(f"置換が1か所も当たりませんでした（開発側のコードが変わった可能性）: {rule}")


def write_asmdefs(spec: dict, package_id: str, dest: Path) -> None:
    for asm in spec.get("asmdefs", []):
        body = {
            "name": asm["name"],
            "rootNamespace": "",
            "references": asm.get("references", []),
            "includePlatforms": ["Editor"] if asm.get("editor") else [],
            "excludePlatforms": [],
            "allowUnsafeCode": False,
            "overrideReferences": False,
            "precompiledReferences": [],
            "autoReferenced": True,
            "defineConstraints": [],
            "versionDefines": [],
            "noEngineReferences": False,
        }
        path = dest / asm["path"]
        write_text(path, json.dumps(body, ensure_ascii=False, indent=4) + "\n")
        if asm.get("udonsharp"):
            # UdonSharp に「このアセンブリを U# として扱う」と知らせる定義アセット
            asmdef_guid = stable_guid(package_id, asm["path"])
            asset_rel = (Path(asm["path"]).parent / asm["udonsharp"]).as_posix()
            write_text(dest / asset_rel, (
                "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!114 &11400000\nMonoBehaviour:\n"
                "  m_ObjectHideFlags: 0\n  m_CorrespondingSourceObject: {fileID: 0}\n  m_PrefabInstance: {fileID: 0}\n"
                "  m_PrefabAsset: {fileID: 0}\n  m_GameObject: {fileID: 0}\n  m_Enabled: 1\n  m_EditorHideFlags: 0\n"
                "  m_Script: {fileID: 11500000, guid: 5136146375e9a0a498a72a0091b40cc1, type: 3}\n"
                f"  m_Name: {asm['name']}\n  m_EditorClassIdentifier: \n"
                f"  sourceAssembly: {{fileID: 5897886265953266890, guid: {asmdef_guid}, type: 3}}\n"))


def remap_guids(package_id: str, dest: Path) -> None:
    """コピーしたメタの GUID を固定値に振り直し、パッケージ内の参照も合わせて書き換える。"""
    mapping: dict[str, str] = {}
    for meta in sorted(dest.rglob("*.meta")):
        rel = meta.relative_to(dest).as_posix()[:-5]
        text, bom = read_text(meta)
        match = GUID_RE.search(text)
        if not match:
            fail(f"GUID が読めないメタ: {meta}")
        new_guid = stable_guid(package_id, rel)
        if match.group(1) != new_guid:
            mapping[match.group(1)] = new_guid
            write_text(meta, GUID_RE.sub(f"guid: {new_guid}", text, count=1), bom)
    if not mapping:
        return
    pattern = re.compile("|".join(mapping))
    for path in sorted(dest.rglob("*")):
        if path.is_file() and path.suffix.lower() in GUID_TEXT_EXTS:
            text, bom = read_text(path)
            new_text = pattern.sub(lambda m: mapping[m.group(0)], text)
            if new_text != text:
                write_text(path, new_text, bom)


def write_package_json(config: dict, package_id: str, dest: Path) -> None:
    spec = config["packages"][package_id]
    path = dest / "package.json"
    version = json.loads(path.read_text(encoding="utf-8"))["version"] if path.exists() else "0.0.0"
    repo = config["repos"][spec["release"]]
    write_json(path, {
        "name": package_id,
        "displayName": spec["displayName"],
        "version": version,
        "unity": "2022.3",
        "description": spec["description"],
        "author": config["author"],
        "license": "MIT",
        "documentationUrl": f"https://github.com/{repo['github']}/tree/main/Packages/{package_id}",
        "changelogUrl": f"https://github.com/{repo['github']}/blob/main/Packages/{package_id}/CHANGELOG.md",
        "vpmDependencies": spec["vpmDependencies"],
    })
    changelog = dest / "CHANGELOG.md"
    if not changelog.exists():
        write_text(changelog, "# 変更履歴\n\nまだ公開していません。\n")


def write_package_readme(config: dict, package_id: str, dest: Path) -> None:
    spec = config["packages"][package_id]
    lines = [f"# {spec['displayName']}", "", f"`{package_id}`", "", *spec["readme"], "",
             "## 必要なもの", "", "- Unity 2022.3"]
    for dep, ver in spec["vpmDependencies"].items():
        lines.append(f"- {dep} {ver}")
    lines += ["", "## ライセンス", "", "MIT License（リポジトリ直下の LICENSE を参照）", ""]
    write_text(dest / "README.md", "\n".join(lines))


def sync_package(config: dict, package_id: str) -> None:
    spec = config["packages"].get(package_id) or fail(f"packages.json に無いパッケージ: {package_id}")
    for repo_key in spec["repos"]:
        dest = package_dir(config, repo_key, package_id)
        dest.mkdir(parents=True, exist_ok=True)
        for child in list(dest.iterdir()):
            if child.name in KEEP_FILES:
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        copy_sources(spec, dest)
        apply_replacements(spec, dest)
        write_asmdefs(spec, package_id, dest)
        write_package_json(config, package_id, dest)
        write_package_readme(config, package_id, dest)
        remap_guids(package_id, dest)
        ensure_metas(package_id, dest)
        print(f"同期しました: {repo_key} / {package_id}")


# ------------------------------------------------------------------ README / ページ

def read_version(config: dict, package_id: str) -> str:
    spec = config["packages"][package_id]
    path = package_dir(config, spec["release"], package_id) / "package.json"
    return json.loads(path.read_text(encoding="utf-8"))["version"] if path.exists() else "-"


def write_repo_readmes(config: dict) -> None:
    for repo_key, repo in config["repos"].items():
        rows = [f"| [{spec['displayName']}](Packages/{pid}) | `{pid}` | {spec['description']} | {read_version(config, pid)} |"
                for pid, spec in config["packages"].items() if repo_key in spec["repos"]]
        lines = [
            f"# {repo['title']}", "",
            f"MetraZero 制作の VRChat {repo['summary']}です。", "",
            "## 収録ツール", "",
            "| ツール | パッケージID | 内容 | バージョン |", "| --- | --- | --- | --- |", *rows, "",
            "## 導入方法（VCC / ALCOM）", "",
            "1. 次の URL を VCC（または ALCOM）の「Packages > Add Repository」に登録する", "",
            f"   `{config['listing']['url']}`", "",
            "   または [こちらのページ](https://metrazero.github.io/vpm-repo/) の「VCC に追加」ボタンから登録できます。", "",
            "2. プロジェクトの「Manage Project」から、使いたいツールを追加する", "",
            "アバター向け（Metlab AVA）とワールド向け（Metlab WLD）は同じ URL で配信しています。",
            "ワールド向けのツールはワールド用 SDK が必要なので、アバター用プロジェクトには入りません（逆も同じ）。", "",
            "## メニュー", "",
            "ウィンドウを持つツールは、すべて `Tools > Metlab` の下にあります。", "",
            "## ライセンス", "", "[MIT License](LICENSE)", "",
        ]
        write_text(Path(repo["local"]) / "README.md", "\n".join(lines))
    print("README を作り直しました")


def write_listing_page(config: dict) -> None:
    listing = json.loads(LISTING_PATH.read_text(encoding="utf-8"))
    url = config["listing"]["url"]
    items = []
    for pid, spec in config["packages"].items():
        versions = listing["packages"].get(pid, {}).get("versions", {})
        latest = max(versions, key=lambda v: tuple(int(x) for x in v.split("."))) if versions else None
        if not latest:
            continue
        repo = config["repos"][spec["release"]]
        kind = "アバター・ワールド両方" if len(spec["repos"]) > 1 else repo["summary"]
        items.append(f'<li><strong>{spec["displayName"]}</strong> <span class="v">v{latest}</span>'
                     f'<span class="k">{kind}</span><br>{spec["description"]}'
                     f' <a href="https://github.com/{repo["github"]}/tree/main/Packages/{pid}">説明</a></li>')
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Metlab</title>
<style>
:root{{--bg:#fafafa;--fg:#222;--sub:#666;--card:#fff;--line:#e3e3e3;--accent:#4b6bfb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16171a;--fg:#eee;--sub:#aaa;--card:#202226;--line:#33363c;--accent:#8aa0ff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,"Hiragino Sans","Yu Gothic UI",sans-serif;line-height:1.7}}
main{{max-width:760px;margin:0 auto;padding:32px 16px}}
h1{{margin:0 0 4px}} p.sub{{color:var(--sub);margin:0 0 24px}}
.add{{display:inline-block;background:var(--accent);color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600}}
code{{background:var(--card);border:1px solid var(--line);padding:2px 6px;border-radius:4px;word-break:break-all}}
ul{{list-style:none;padding:0}} li{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}}
.v{{color:var(--sub);margin-left:8px}} .k{{font-size:.8em;border:1px solid var(--line);border-radius:99px;padding:1px 8px;margin-left:8px;color:var(--sub)}}
a{{color:var(--accent)}}
</style></head><body><main>
<h1>Metlab</h1>
<p class="sub">{config["listing"]["description"]}</p>
<p><a class="add" href="vcc://vpm/addRepo?url={url}">VCC に追加</a></p>
<p>手動で登録する場合は、VCC / ALCOM の「Add Repository」に次の URL を入力してください。<br><code>{url}</code></p>
<h2>ツール一覧</h2>
<ul>
{chr(10).join(items) if items else "<li>まだ公開しているツールはありません。</li>"}
</ul>
<p><a href="https://github.com/MetraZero/Metlab-AVA">Metlab AVA（アバター向け）</a> ／ <a href="https://github.com/MetraZero/Metlab-WLD">Metlab WLD（ワールド向け）</a></p>
</main></body></html>
"""
    write_text(PAGE_PATH, html)


# ------------------------------------------------------------------ build / release

def build_zip(config: dict, package_id: str) -> Path:
    spec = config["packages"][package_id]
    src = package_dir(config, spec["release"], package_id)
    version = json.loads((src / "package.json").read_text(encoding="utf-8"))["version"]
    DIST_DIR.mkdir(exist_ok=True)
    output = DIST_DIR / f"{package_id}-{version}.zip"
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in src.rglob("*") if p.is_file()):
            info = ZipInfo(path.relative_to(src).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(f"ZIP を作りました: {output}")
    return output


def release(config: dict, package_id: str, version: str, note: str) -> None:
    spec = config["packages"].get(package_id) or fail(f"packages.json に無いパッケージ: {package_id}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail("バージョンは 1.0.0 の形で指定してください")
    tag = f"{package_id}-v{version}"
    release_repo = config["repos"][spec["release"]]
    listing = json.loads(LISTING_PATH.read_text(encoding="utf-8"))
    if version in listing["packages"].get(package_id, {}).get("versions", {}):
        fail(f"{package_id} {version} は配信リストに登録済みです")

    # 1. バージョンと変更履歴を書き、配布用リポジトリをコミット・push
    today = date.today().isoformat()
    for repo_key in spec["repos"]:
        dest = package_dir(config, repo_key, package_id)
        manifest_path = dest / "package.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = version
        write_json(manifest_path, manifest)
        changelog = dest / "CHANGELOG.md"
        body = changelog.read_text(encoding="utf-8") if changelog.exists() else "# 変更履歴\n"
        body = body.replace("# 変更履歴\n\nまだ公開していません。\n", "# 変更履歴\n")
        body = body.replace("# 変更履歴\n", f"# 変更履歴\n\n## {version} - {today}\n\n- {note}\n", 1)
        write_text(changelog, body)
    write_repo_readmes(config)
    for repo_key in spec["repos"]:
        root = Path(config["repos"][repo_key]["local"])
        run(["git", "add", "-A"], root)
        run(["git", "commit", "-m", f"{spec['displayName']} v{version}: {note}{COMMIT_TRAILER}"], root)
        if repo_key == spec["release"]:
            run(["git", "tag", "-a", tag, "-m", f"{spec['displayName']} v{version}"], root)
        run(["git", "push", "origin", "main", "--follow-tags"], root)

    # 2. ZIP を作って GitHub Release に載せる
    zip_path = build_zip(config, package_id)
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    run(["gh", "release", "create", tag, str(zip_path), "--repo", release_repo["github"],
         "--title", f"{spec['displayName']} v{version}", "--notes", note], HUB_ROOT)

    # 3. 配信リストに追加して公開
    manifest = json.loads((package_dir(config, spec["release"], package_id) / "package.json").read_text(encoding="utf-8"))
    manifest["url"] = f"https://github.com/{release_repo['github']}/releases/download/{tag}/{zip_path.name}"
    manifest["zipSHA256"] = sha256
    listing["packages"].setdefault(package_id, {"versions": {}})["versions"][version] = manifest
    write_json(LISTING_PATH, listing)
    write_listing_page(config)
    run(["git", "add", "-A"], HUB_ROOT)
    run(["git", "commit", "-m", f"{spec['displayName']} v{version} を配信リストに追加{COMMIT_TRAILER}"], HUB_ROOT)
    run(["git", "push", "origin", "main"], HUB_ROOT)
    print(f"公開しました: {spec['displayName']} v{version}")


# ------------------------------------------------------------------ main

def main() -> None:
    parser = argparse.ArgumentParser(description="Metlab 配布パッケージの管理ツール")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync"); p_sync.add_argument("package")
    sub.add_parser("readme")
    p_build = sub.add_parser("build"); p_build.add_argument("package")
    p_rel = sub.add_parser("release"); p_rel.add_argument("package"); p_rel.add_argument("version"); p_rel.add_argument("note")
    args = parser.parse_args()
    config = load_config()

    if args.command == "sync":
        targets = list(config["packages"]) if args.package == "all" else [args.package]
        for package_id in targets:
            sync_package(config, package_id)
        write_repo_readmes(config)
    elif args.command == "readme":
        write_repo_readmes(config)
        write_listing_page(config)
    elif args.command == "build":
        build_zip(config, args.package)
    elif args.command == "release":
        release(config, args.package, args.version, args.note)


if __name__ == "__main__":
    main()
