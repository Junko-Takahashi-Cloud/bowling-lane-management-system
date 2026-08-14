# Phase3-1 実装共通ルール(4AI分担用)

このドキュメントは `phase3_design_spec.md` を前提とした「実装ルールの整理」のみを目的とする。コード実装は含まない。仕様書に記載のない事項は「変更提案」として明示し、担当者が独断で確定しない。

---

## 1. ER・テーブル定義の実装上の確定事項

`phase3_design_spec.md` のPhase3-1テーブル(staff, lane, class_group, class_session, class_attendance, checkin, payment, pricing_rule)をそのまま正とする。追加・変更は下記「6. 変更提案」に記載する形式で提案すること。

- 主キーは全テーブル `id`(integer, auto increment)で統一
- 外部キーは `<参照先テーブル単数形>_id` の命名で統一(例:`class_group_id`, `lane_id`)
- 日時カラムは全て UTC 保存、表示時にJSTへ変換する方針(**変更提案**:仕様書に明記がなかったため確認要)

---

## 2. SQLAlchemyモデルの構成

- 1テーブル = 1ファイル。`app/models/` 配下に `staff.py`, `lane.py`, `checkin.py` のように配置
- クラス名はテーブル名のPascalCase(例:`class_group` → `ClassGroup`)
- Base共通カラム(`id`, `created_at`, `updated_at`)は `app/models/base.py` の `BaseModel` に共通定義し、各モデルが継承する(**変更提案**:仕様書に`created_at`/`updated_at`の明記なし。監査目的で追加を提案)
- Enumは Python の `enum.Enum` を使い、`app/models/enums.py` に集約

---

## 3. Pydantic Schemaの構成

- `app/schemas/` 配下、テーブルごとに1ファイル
- 命名規則:
  - 作成用:`<Model>Create`(例:`CheckinCreate`)
  - 更新用:`<Model>Update`
  - レスポンス用:`<Model>Read`
- レスポンスは基本的に `Read` スキーマのみを返す(内部専用カラムは含めない)

---

## 4. APIの命名・レスポンス形式

- REST形式、ベースパスは `/api/v1/`
- リソース名は複数形・snake_case(例:`/api/v1/checkins`, `/api/v1/class_groups`)
- レスポンスは統一エンベロープ形式を提案(**変更提案**):
  ```json
  { "data": {...}, "error": null }
  ```
  エラー時:
  ```json
  { "data": null, "error": { "code": "...", "message": "..." } }
  ```
- ステータスコード:200(成功)/400(入力エラー)/404(存在しない)/409(競合、例:満員・二重予約)

---

## 5. ディレクトリ構成(提案・要確認)

```
app/
  models/       # SQLAlchemyモデル
  schemas/      # Pydanticスキーマ
  routers/      # APIエンドポイント(機能グループ単位)
  services/     # 業務ロジック(判定ロジック等)
  db/           # DB接続・マイグレーション
tests/
```

第一弾・第二弾の既存構成(FastAPI + SQLite + Streamlit)と揃える必要があるため、**このディレクトリ構成は変更提案とし、既存リポジトリ構成を確認の上、純子さんの承認を得てから確定する**。

---

## 6. 命名規則まとめ

- テーブル・カラム:snake_case
- モデルクラス:PascalCase
- APIパス:snake_case・複数形
- Enum値:英語・snake_case(下記7で定義)

---

## 7. Enum・statusの値(提案)

仕様書は日本語の状態名で記述されているため、コード上の値を以下のように統一することを提案する(**変更提案**:実際の値は4AIですり合わせの上、純子さんの確認を推奨)。

- `lane.status`:`available` / `in_use` / `broken` / `maintenance`
- `checkin.status`:`checked_in` / `in_use` / `checked_out`
- `class_group.status`:`recruiting` / `confirmed` / `released`(締切未成立で開放)
- `class_session.status`:`scheduled` / `completed` / `cancelled`
- `class_attendance.attendance_status`:`all_present` / `partial_absent_continue` / `partial_absent_slide`
- `payment.payer_type`:`class` / `checkin`
- `payment.payment_timing`:`prepaid` / `postpaid`
- `payment.payment_method`:`cash` / `card` / `e_payment` / `unpaid`

---

## 8. 各機能の責務分担(4AI)

| グループ | 担当領域 | 対象テーブル |
|---|---|---|
| A | レーン・受付・会計 | lane, checkin, payment, pricing_rule |
| B | 教室・出欠 | class_group, class_session, class_attendance |
| C(Claude担当) | スタッフ・コーチ管理 | staff |
| D | ダッシュボード・表示系 | 上記テーブルを横断参照する画面のみ、テーブル新規作成なし |

※コーチのシフト管理(coach_shift等)はPhase3-2のため、今回のPhase3-1分担には含めない。

---

## 9. Claude担当範囲(明確化)

**担当:グループC「スタッフ管理」のみ**

- 対象テーブル:`staff`(id, name, pin_code, is_active)
- 実装範囲:
  - `staff` のSQLAlchemyモデル・Pydanticスキーマ
  - PINログインAPI(`POST /api/v1/staff/login`)の仕様定義(4桁PIN照合、階層管理なし)
  - `is_active` によるログイン可否判定ロジックの仕様
- 範囲外(明示的に含めない):
  - コーチのシフト管理(coach_shift, coach_shift_exception, staff_attendance)→ Phase3-2のため今回対象外
  - 他グループ(A・B・D)のテーブル・API実装

---

## 10. 変更提案まとめ(要・純子さん確認)

1. 日時のUTC保存方針
2. `created_at`/`updated_at`の共通カラム追加
3. APIレスポンスのエンベロープ形式
4. ディレクトリ構成(既存リポジトリとの整合確認が必要)
5. Enum値の英語表記(実装者間ですり合わせ推奨)

これらは仕様書に明記がなかったため、4AI実装開始前に純子さんの確認・承認を推奨する。
