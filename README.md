# Al Kass Colab Recorder

Al Kass Shoof のチャンネル `one`〜`eight` を、指定した **Asia/Amman の時刻範囲**でGoogle ColabからGoogle Driveへ保存する、共有用の録画テンプレートです。

録画データ、Cookie、Token、個人のGoogle Drive IDはこのリポジトリに含まれません。利用者は自身の視聴権限と配信元の利用条件を確認したうえで使用してください。DRMやアクセス制限を迂回するツールではありません。

## Colabで開く

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KOBAYU0602/alkass-colab-recorder/blob/main/notebooks/Alkass_Controller.ipynb)

1. 上のリンクを開き、`ファイル → ドライブにコピーを保存`を選びます。
2. 鍵アイコンのColab Secretsへ `ALKASS_COOKIES` を登録します。値は、自分のブラウザーから書き出したNetscape Cookieファイルの全文です。
3. セル1の `JOBS` にチャンネル、開始・終了、ファイル名を入力します。
4. `RUN_JOBS = True` にして、セルを上から順に実行します。
5. 完成MP4は既定で `/MyDrive/Alkass Recordings` に保存されます。

```python
JOBS = [
    {
        "channel": "two",
        "start": "2026-08-21 13:55",
        "end": "2026-08-21 15:40",
        "name": "21082026 Team A vs Team B Alkass Two",
    },
]
RUN_JOBS = True
```

通常の試合でキックオフだけ分かっている場合は、開始5分前から試合開始105分後まで、合計110分を目安にしてください。

## 機能

- チャンネル `one`〜`eight` のジョブ単位指定
- 1080p優先のHLS選択
- `PROGRAM-DATE-TIME` による現実時刻との対応
- 未来区間の開始待機と、配信元DVR窓に残る過去区間の回収
- Google Drive上のセグメント台帳による中断再開
- SHA-256、ギャップ検出、重複回避
- ffmpegによるMP4化とffprobe検証
- 同名の読めるMP4がある場合は上書きせずスキップ

配信元のDVR保持時間を延ばすことはできません。実測では約60分のことがあり、古い区間は回収できない場合があります。`STRICT_PAST_START=True` では、指定開始点が失われていると不完全ファイルを作らず停止します。

## 認証情報を入れないための設計

優先順位は次のとおりです。

1. Colab Secret `ALKASS_COOKIES`
2. 利用者自身のDriveに置いた `/MyDrive/Cookies_Alkass.txt`
3. Cookieなし（無料チャンネルのみ）

Cookie本文やBearer Tokenは状態JSON、台帳、ログへ書きません。Colab Secretから生成する一時Cookieファイルは `/content` に作られ、ランタイム終了時に消えます。

公開・再共有する前に、必ずセル出力を消し、次を実行してください。

```bash
python tools/sanitize_notebook.py your-copy.ipynb --output sanitized.ipynb
python tools/scan_secrets.py sanitized.ipynb
```

過去にCookieやTokenを貼り付けたノートブックは、その値を削除するだけでなく、該当セッションをログアウトなどで失効させてください。

## リポジトリ構成

```text
notebooks/Alkass_Controller.ipynb   配布用Colab
scripts/build_alkass_controller.py  ノートブックの再生成元
examples/job.example.json           ジョブ設定例
tools/sanitize_notebook.py          出力・実行履歴の除去
tools/scan_secrets.py                秘密情報らしき値の検査
SECURITY.md                          安全な共有方法
```

## ノートブックを再生成する

```bash
python scripts/build_alkass_controller.py
python tools/scan_secrets.py .
```

## ライセンス

MIT License。配信映像の権利やサービス利用権限は、このソフトウェアのライセンスには含まれません。
