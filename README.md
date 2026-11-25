# 启衡材料老化复验台账

台架员从当地工作表导入同批耐候薄膜试片的复验。夜班分析员收齐两份固定站件后复核双超限风险。质控员依据定稿执行隔离、放行或待复核，并在次日按原报告号查回当时采用的站件和成功回执。

## 运行

使用 Python 3.11 标准库。在项目根目录运行：

```sh
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 是运行环境提供的完整回归入口。测试在 `tests` 包中。演示用临时目录保存批次档、两台架私有库及中心库，结束后清理。`python3 -B demo.py --directory ./work --batch FILM-02` 可保存演示档案。指定目录中的既有数据按普通接口处理。若指定批号已经有台架初版，请用新的演示批号。初始化可重复执行，每次只补建缺失结构。

## 实际交班

1. 台架员登记批次、两条参考名称和台账隔离线。名称次序不影响批次档案的身份。
2. 两台架导入各自的工作表。初次导入的前版留空，勘误明确指向同台架同批的前版。每次导入是可单独发行的整组快照。
3. 台架员按修订号发行，或按旧发行号补发。原行、未匹配试验及私有试验过程留在站端。
4. 夜班独立实收固定件，各站可以关源。同件重送得到已有实收号。
5. 分析员提交有序实收对、四状态先验及本次隔离线。按具名状态核定，稿与执同时签存。
6. 质控员按正式裁决执行。白班收到不同发行的勘误件时可以再签一份，重开中心库后按旧报告号仍可领取原稿和回执。

## Python 接口

调用者用 `sqlite3.connect(path)` 打开各自的库，并负责关闭连接。以相应连接构造 `BatchStore`、`RevisionStore`、`IssueStore`、`IntakeArchive`、`ReportStore`，然后各调用 `initialize()`。修订及发行存储用同一台架连接，实收与报告存储用同一中心连接。初始化、登记、修订、发行、实收和核定由各存储管理自己的提交边界，调用时连接中应无外部未结束事务。台架标识在同批交班内唯一标识一个发行来源，修订、发行、实收和报告编号分别在自己的库内分配。

| 操作 | 输入与结果 |
| --- | --- |
| `batch.catalog.register(catalog, batch_id, reference_names, isolation_line)` | 两个不同的具名参考及合法隔离线，返回 `BatchRecord`。同号同参返回原档，同号异参报 `ValueError`。`get_batch(catalog, batch_id)` 读取已登记档。 |
| `station.revisions.revise(catalog, revisions, batch_id, station, rows, *, parent_id=None, reference_names=None)` | 返回 `StationRevision`，其 `revision_id` 可用于发行。每行形如 `((0, 1), '1/2', True, False)`，依次为状态、权重、是否匹配、是否超限。行状态按 `reference_names` 的声明顺序解释，省略时沿用台账按名称排序的参考。允许空试验组，代表没有本站观测支持。`load_revision` 可按修订号取整组。 |
| `station.issue.issue(issues, revision_id)`、`station.issue.reissue(issues, issue_id)` | 两者返回 `FrozenIssue`。使用 `.raw` 传送固定件字节。重复指定同一修订或按发行号补发均返回原件。 |
| `intake.receipt.receive(archive, raw)` | 核验并保存固定件，返回 `ReceivedItem`，其中 `receipt_id` 是中心实收号。`get_received(archive, receipt_id)` 读取该已验原件。 |
| `risk.request.assess(archive, reports, request)` | `AssessmentRequest((left_id, right_id), JointPrior(batch_id, make_reference_pair(names), masses), isolation_line)` 指定本次参数。`masses` 按声明参考次序依次为 00、01、10、11。返回 `ReportBundle`，其 `report.draft` 包含有序出处、精确先验、风险及裁决，`receipt` 是成功回执。 |
| `report.retrieve.read(reports, report_id)` | 返回原样的 `ReportBundle`。有效编号在库中找不到时返回 `None`。 |

批号、参考名和台架标识为非空可打印字符串，首尾无空格。公开编号为正整数。状态位为整数 0 或 1，试验标记为布尔值。Python 接口的精确数值接受 `Fraction`、整数或 `Fraction` 可解析的字符串，例如 `1/4`、`0.25`。隔离线须在 `[0,1]`。非法内容、批次错配、参考错配及同台架双件报 `ValueError`。按号查询未知批次、修订、发行或实收报 `KeyError`。SQLite 写入错误由调用者接收，未提交的当次业务写入回滚。

## V1 固定件

固定件是 UTF-8 JSON 对象。外层字段为 `version`（整数 1）、`batch_id`、`station`、`revision_id`、`issue_id`、`sha256` 和 `body`。`body` 是正文的原始 JSON 文本字符串，摘要为该字符串的 UTF-8 字节的 SHA-256 小写十六进制值。重送按批号、台架、发行号及已核验原正文识别，中心归档首次实收的完整字节。

正文包含同样的四个出处字段 `batch_id`、`station`、`revision_id`、`issue_id`，还包含两条名称组成的 `references` 数组和 `evidence` 数组。证据数组列出四个不同的状态，每项为 `state`（按声明名称排列的两位整数）、`likelihood`（非负精确有理数）和 `exceedance`（介于零与 `likelihood` 之间的精确有理数）。发行以字符串编码质量，核定也接受 JSON 整数。实收先核验外层、摘要和共有出处，核定再校验四状态证据。外层或正文的重复 JSON 键均拒绝。

## 核算与质控

匹配行的权重在每个状态求和得到证据质量 L，该状态匹配行中标为超限的子集求和得到 H。质量无量纲，保留一个站件内的共同尺度。给定共同参考状态，两站私有试验独立。按名称对齐以后，对每个状态用本次先验乘两站的 L 得到共同证据贡献，用同一先验乘两站的 H 得到双超限贡献。前者相加为 D，后者相加为 N。D 为正时精确风险为 N/D。D 为零签 `incompatible`，风险为空，裁决 `review`。可证风险的状态为 `established`，达到本次隔离线时裁决 `isolate`，低于时裁决 `release`。

演示固定使用两个参考 A、B_REF。甲初版在 00、11 各有质量 1，仅 11 超限。乙在 00、11 的质量为 1、1/2，仅 11 超限。均匀先验下 D=3/8、N=1/8，风险为 1/3，超过隔离线 1/4。将同一双件的先验改成 `(1/4, 0, 0, 3/4)`，风险为 3/5，恰达本次 3/5 的隔离线。甲勘误只有 01、10 的观测支持，与乙无共同支持。演示会核对三份实际裁决，也会重开中心库核对旧稿和原回执。
