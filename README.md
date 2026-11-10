# CPH JRA Data Foundation

JRA公式データを取得・検査し、年度別の `YYYY_JRA_MASTER.zip` を出力するリポジトリです。TRACEの学習・予想は別の工程です。

普段の更新は [JRA 原本MASTER・手動差分更新](https://github.com/yajimuch-max/CPH-JRA-Data-Foundation/actions/workflows/jra_original_master.yml) を使います。設定と成果物の確認手順は [GitHub運用ガイド](GITHUB_OPERATIONS_JA.md) を参照してください。

| 場所 | 役割 |
| --- | --- |
| `jra_original_master_engine.zip` | データ取得・SQLite・原本出力のパッケージ |
| `scripts/current_refund_repair.py` | 2026年の通常更新後に公式返還を照合して再出力 |
| `scripts/repair_integrity.py` | 人物・返還修復で既存データが保持されたことを確認 |
| `scripts/historical_person_export.py`、`scripts/refund_repair_export.py` | 過去年原本の修復用コマンド |
| `scripts/audit_trace_*.py` | MASTERとTRACE側の履歴・特徴表を読み取り専用で照合 |
| `.github/workflow-archive/` | 過去の一括修復用Actionsの定義 |

PRでは、取得パッケージと `tests/` の単体テストをオフラインで自動実行します。
