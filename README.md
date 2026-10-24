# Metlab 配信リスト

MetraZero 制作の VRChat 向けツール（Metlab AVA／Metlab WLD）を VCC・ALCOM から入れるための配信リストです。

## 登録方法

VCC（または ALCOM）の「Packages > Add Repository」に次の URL を登録してください。

`https://metrazero.github.io/vpm-repo/index.json`

[ツール一覧ページ](https://metrazero.github.io/vpm-repo/) の「VCC に追加」ボタンからも登録できます。

## ツールの置き場所

- [Metlab AVA](https://github.com/MetraZero/Metlab-AVA)：アバター向け
- [Metlab WLD](https://github.com/MetraZero/Metlab-WLD)：ワールド向け

## このリポジトリの中身

| ファイル | 内容 |
| --- | --- |
| `index.json` | VCC が読む配信リスト |
| `index.html` | ツール一覧ページ |
| `Tools/packages.json` | 配布するツールの定義（どこからコピーし、どう書き換えるか） |
| `Tools/metlab.py` | 同期・ZIP 作成・公開を行うスクリプト |
