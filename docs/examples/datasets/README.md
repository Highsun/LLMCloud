# M1 契约样例

这些文件用于协作和接口验证，是固定演示样例，不是实际上传记录。M1-03 已实现真实 API，响应以本次请求生成的 ID、时间和统计值为准。正式格式样例仍为 [../train.jsonl](../train.jsonl)。

| 文件 | 含义 |
| --- | --- |
| valid-minimal.jsonl | input 缺省合法，读取时视为 "" |
| invalid-missing-output.jsonl | 缺 output；422/INVALID_DATASET，missing |
| invalid-input-null.jsonl | input 为 null；422/INVALID_DATASET，invalid_type |
| invalid-extra-field.jsonl | 未知键 messages；422/INVALID_DATASET，extra_field |
| upload-response.json | POST/详情的共同响应；由 train.jsonl 统计值生成 |
| list-response.json | 一条 DatasetSummary 的分页结果 |
| empty-page.json | total=0、page=1 的空列表 |
| beyond-last-page.json | page 超出末页，保留原页码、items=[] |
| error-response.json | 文件记录缺字段的公共错误结构 |

响应 JSON 由 `scripts/export_dataset_contract.py` 生成，不手改；原始正反 JSONL 可人工维护。无效文件只作为测试输入，不是可上传成功的演示数据。
