# Metlab 配布の運用ルール

ユーザー（MetraZero）が「これをリポジトリ化して」「〜を更新して」と言ったときの手順書。

## 全体の形

| 場所 | 役割 |
| --- | --- |
| 開発プロジェクト `D:\Unity\Project\MetAvatars`（アバター）／`D:\Unity\Project\Metroom - Far Sky -`（ワールド） | 開発の本体。常に最新。Assets 内で自由に開発している |
| `D:\Unity\Metlab-AVA`（GitHub `MetraZero/Metlab-AVA`） | アバター向けの配布用。**直接編集しない** |
| `D:\Unity\Metlab-WLD`（GitHub `MetraZero/Metlab-WLD`） | ワールド向けの配布用。**直接編集しない** |
| `D:\Unity\vpm-repo`（GitHub `MetraZero/vpm-repo`、Pages 公開） | 配信リスト `index.json` と、配布用の設定・スクリプト |

- 両方で使うツールは AVA と WLD の両方に同じ内容で置き、配信リストには AVA 側の Release を載せる（`packages.json` の `release`）
- ユーザーが指定したツールだけを配布する。勝手に増やさない
- 旧リポジトリ `MetraZero/Metlab`・`MetraZero/Metlabo` はアーカイブ済み。`D:\Unity\Metlab` はその手元の控え（もう参照されていない）

## 名前のルール

- ツール名は「〜やつ」。ひらがな＋「を」あり（例：トグルをつくるやつ、房を選んで髪色をかえるやつ）
- メニュー：`Tools/Metlab/<ツール名>`
- パッケージID：アバター向け `com.metlab.ava.<英名>`、ワールド向け `com.metlab.wld.<英名>`、両方 `com.metlab.<英名>`
- 名前空間：`Metlab.<英名>`。名前空間の無いスクリプトは `wrapNamespace` で包む（UdonSharp は同名クラスがあると衝突する）
- アセンブリ名：`Metlab.<英名>`（ランタイム）／`Metlab.<英名>.Editor`
- 生成物の保存先：`Assets/MetlabGenerated/<ツール名>/`
- 表記は Metlab に統一（Metlabo・メトラボ・MET などは使わない）。シェーダー名も `Metlab/〜`
- 試作段階のもの（開発側のコメントに「骨組み段階」など）は、開発側のバージョン（0.x）のまま公開し、`packages.json` に `"beta": true` を付ける（一覧ページで名前の横に黄色の BETA、README の先頭に試作版の注意書き）

## 一覧ページ（index.html）の記載ルール

- 見出しはロゴ画像 `logo.webp`（ダークモードでは反転表示）。サブタイトルは付けない
- 各ツールは「名前（BETA）・バージョン・種別」→ 説明文 → 改行して「解説ページ」リンク（パッケージの README へ）
- ページは `metlab.py` が自動で作る。手で直さず、`write_listing_page` を直す

## 新しく「リポジトリ化して」と言われたら

1. 開発プロジェクトで対象ツールの場所・依存（MA、VRC SDK、UdonSharp など）・メニュー・保存先パス・名前空間を確認する
2. `Tools/packages.json` に項目を足す
   - `sources`：コピー元。`_Generated`・`_Backups`・個人のアバター名が入ったデータなどは `exclude` で外す
   - `asmdefs`：開発側の asmdef は `exclude` で外し、ここで作り直す（UdonSharp なら `udonsharp` で定義アセットも作る）
   - `replace`：メニュー・名前空間・保存先・ウィンドウ名を上のルールに合わせる。1か所も当たらないとエラーで止まる
   - `readme`：使い方（日本語）
3. `python Tools/metlab.py sync <ID>` で同期する
4. 動作確認（下記）
5. `python Tools/metlab.py release <ID> 1.0.0 "初回公開"` で公開する

## 「更新して」と言われたら

1. `python Tools/metlab.py sync <ID>`（置換が当たらなくなったら、開発側のコードの変化に合わせて `packages.json` を直す）
2. 動作確認（下記）
3. `git -C <配布用リポジトリ> diff` で変更点を確認し、バージョンを決める（修正=パッチ、機能追加=マイナー、互換性が壊れる=メジャー）
4. `python Tools/metlab.py release <ID> <バージョン> "<更新内容>"`

## 動作確認のやり方

- Unity が開いていないことを確認する（`<プロジェクト>\Temp\UnityLockfile` が無いこと）。開いていたらユーザーに閉じてもらう
- 開発プロジェクトの `Packages/manifest.json` と `packages-lock.json` を控え、`"<ID>": "file:D:/Unity/Metlab-AVA/Packages/<ID>"` を一時的に足す
- `"C:\Program Files\Unity\Hub\Editor\2022.3.22f1\Editor\Unity.exe" -batchmode -quit -projectPath <プロジェクト> -logFile <ログ>` を実行し、ログの `error CS` が 0 件か確認する
- 終わったら manifest と lock を控えから戻し、もう一度バッチモードで開いて 0 件を確認する

## 注意

- 開発プロジェクトに、公開した Metlab のパッケージを VCC から入れない（開発版と同じものが2つになる）
- `legacyFolders` は使わない（旧リストは `Assets/Metlab` を指定しており、入れると開発フォルダが消える危険があった）
- GUID は「パッケージID＋相対パス」から決まる固定値。ファイル名を変えると GUID も変わる
- 公開（release）は GitHub へ push・Release 作成・配信リスト更新まで一気に行う。ユーザーの依頼があったときだけ実行する
