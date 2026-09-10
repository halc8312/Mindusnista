# 原作セーブ共有の調査と受入条件

確認日: 2026-09-10。参照は Mindustry **v159.7**、完全コミット
`c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c`。GitHub API の tag ref と固定版ソースを取得して確認した。
本資料は実装前の調査。原作ファイルの読込・書出し・iOS/Steam との共有成功は未確認。
完全移植の目標には超大規模セーブと全機能を含み、未対応機能の削除を最終仕様にしない。

## 現状と互換性の単位

現在の `src/mindusnista/app.py` は `mindustry-pythonista-dev` / schema 1 の独自 JSON。
`World.from_dict()` は原作 `.msav` を未対応として拒否する。旧 schema 1 の読込・保存・続行を維持し、
原作形式を別 codec として追加する。拡張子変更や同じ版番号の記載だけでは互換にならない。

| 共有対象 | 原作ソースから確認した範囲 |
|---|---|
| 単独 `.msav` | 圧縮されたワールド保存。meta、patches、content、map、entities、markers、custom を含む |
| キャンペーン全体 | 複数の sector 保存に加え、研究投入量・unlock・sector info などの settings が必要 |
| 全データ export ZIP | 原作 UI は settings、saves、maps、mods、schematics、asset-cache を収録する |
| 外部 asset 付き保存 | 埋め込みデータまたは SHA256 による cache 参照。ファイル単体で完結するとは限らない |

研究投入量は `TechNode.save()`、unlock は `UnlockableContent`、sector info は `Sector.saveInfo()` が
`Core.settings` に保存する。単独 `.msav` の往復成功をキャンペーン全体の共有成功として扱わない。
原作の全データ import は既存 saves と asset-cache を削除するため、受入試験は別の検証用データ領域で行う。

## 固定版形式で外せない項目

- `SaveIO` は inflate 後に `MSAV` ヘッダと整数の形式 version を読む。現 writer は **Save13**。
  Save1～Save12 の reader も登録される。ゲーム build、ファイル形式 version、個別 revision を区別する。
- 現 region 順序は `meta → patches → content → map → entities → markers → custom`。
  region/chunk は長さ付き。Java の数値表現・符号・文字列 IO、長さの解釈を一致させる。
- content は種別ごとの名前配列から保存中 ID の一時写像を作る。Python 側の独自 ID を流用しない。
- map は床・overlay・block の連続圧縮、multiblock 中心、追加 tile データを持つ。
  建物は共通 IO とブロック固有 revision の両方が必要。HP・team・rotation・有効状態・在庫・液体・電力等を保持する。
- entities は classId、entity ID、custom mapping、建設計画/config を扱い、読込後に相互参照を復元する。
  entity serializer は生成コードと `annotations/src/main/resources/revisions` も照合する。
- meta の rules・wave・tick・stats・player team、logic、markers、MOD の custom chunks も対象にする。
- Save13 の patches は asset の埋め込み、または 32-byte SHA256 の cache 参照を持つ。
  patch をロードしてから rules を解釈する。原作の単独 export は、プレイ中かつ外部 asset がある場合に埋込保存する。

## 無損失を確認しながら広げる codec

1. 原本を変更せず、形式・領域・依存 content を診断する。未対応部分は名前・ID 写像・revision・元バイト位置とともに記録する。
2. 保存を表す中間構造を作り、既知データと未解釈のデータを保持する。原本・副本・作業中ワールドを別に管理する。
3. 無操作の読み書きを比較し、原作 reader でも復元する。圧縮結果や時刻等の差と、ゲーム状態の欠落を区別する。
4. 対応した状態を実際に更新して往復し、各機能の受入範囲を広げる。最終目標は全機能・全共有対象への対応。

原作 reader には未知 custom chunk や未対応 entity を読み飛ばす分岐がある。
それをそのまま模倣し、消失した状態を書き戻して「互換」としない。
未解釈データの保管だけでは、プレイ後の ID・参照・依存状態の整合性は保証できない。
整合性を扱えるまで原本と無変更返却を保持し、未対応内容を含む状態の更新・互換書出しは成功扱いしない。
この段階の未対応は実装課題として残し、機能制限を完成仕様へ変更しない。

## S-01: 次の実装は原作ファイルの読取診断

実装単位は headless の読取 inspector と fixture 試験。ゲーム中の World や既存セーブを変更しない。
入力原本は保持し、圧縮形式・ヘッダ・version・region 長・meta・content 名・asset 依存の診断結果を返す。
未対応 version、途中切断、領域長不整合は理由付きで停止し、部分読込を成功としない。
MOD/patch/外部 asset の存在を報告するが、この段階で適用やゲームへの import は行わない。
原作出力の小規模 fixture と大規模 fixture を用意し、版・生成条件・SHA256・利用許諾を記録する。
正常・破損入力、原本不変、旧 schema 1 継続を試験し、読取時間・展開量・ピークメモリーも測る。
大規模入力は逐次展開を検討し、現 JSON 用 `MAX_SAVE_BYTES` を原作世界の完成仕様上限として転用しない。
資料取得・合成ヘッダ検査・独自 JSON 試験だけで S-01 の原作 fixture 受入を完了としない。

## iOS / Steam / Pythonista の往復受入条件

| 試験 | 合格に必要な観測 |
|---|---|
| 原作 iOS ↔ Steam | 実アプリ build、content/MOD 版、asset 条件を揃え、原作間の読込・再開・再保存を確認 |
| 原作 → Python → 原作 | 単独 `.msav` を無操作で往復し、原作 reader が復元。個数・ID・参照・設定・地形・各保存状態が一致 |
| Python → 原作 → Python | Python writer の出力を原作で開き再保存し、Python が状態を復元 |
| プレイ後の往復 | 建設・破壊・搬送・戦闘・logic 等を実行後に再開。原作の保存再開動作との差を記録 |
| キャンペーン往復 | 複数 sector、研究投入量、unlock、sector info、asset を含めて復元・続行できる |
| 超大規模往復 | 欠落・暗黙の設備削除・ファイル破損なし。保存/読込時間、停止時間、ピークメモリーを実機で記録 |

最初は同じ固定版で比較し、別 build・旧形式・各 MOD 種別は対応表を広げる。
時刻等の正当に変わる項目、原作の正規化、浮動小数点の比較条件は根拠付きで記録する。
ファイルが開くこと、原作と同じ version を出力すること、PC 模擬試験の成功だけでは合格にしない。
現在、上表の三環境での実往復と大規模保存の実機結果はいずれもない。

## 一次資料（上記固定コミット）

- [SaveIO.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/io/SaveIO.java)、[Save13.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/io/versions/Save13.java)
- [SaveVersion.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/io/SaveVersion.java)、[SaveFileReader.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/io/SaveFileReader.java)
- [BuildingComp.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/entities/comp/BuildingComp.java)、[EntityProcess.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/annotations/src/main/java/mindustry/annotations/entity/EntityProcess.java)
- [Saves.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/game/Saves.java)、[SettingsMenuDialog.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/ui/dialogs/SettingsMenuDialog.java)
- [Sector.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/type/Sector.java)、[TechTree.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/content/TechTree.java)、[UnlockableContent.java](https://github.com/Anuken/Mindustry/blob/c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c/core/src/mindustry/ctype/UnlockableContent.java)
