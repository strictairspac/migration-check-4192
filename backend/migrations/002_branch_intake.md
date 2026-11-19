# Schema v2 — 分院整批接收

在 v1 基础上新增：

- `branch_registrations`：分院预先登记的来源摘要，唯一键 `(branch_code, original_run_id)`。登记后同一来源只能以同一摘要接收，换内容即拒收。
- `intake_batches`：一次整批接收，保存回执号、内容指纹、整体结果与逐项结果。回执号与内容指纹在 `status='accepted'` 时唯一（部分唯一索引），拒收批次不占用回执，可修正后重试。
- `intake_items`：批次内每份原件，保存来源、留存原件 JSON、摘要、本地运行号、逐项状态（accepted/existing/rolled_back/rejected）与拒收原因。

`runs` 增加：
- `batch_id` / `mapping_id` 改为可空（分院运行不来自本地批次/映射）。
- `origin`：`local` 或 `branch`。
- `branch_code`、`original_run_id`：分院来源；唯一键 `(branch_code, original_run_id)` 保证同号不同院各自入库、同院同号只入库一次。
- 分院运行沿用 `runs.result.checksum / accepted_rows` 与 `target_rows`，因此原有目标表读取、备份下载和管理员回传恢复流程可直接使用；`result.backup` 的 `run_id` 写为本地运行号，`original_run_id` 保留分院原号。

整批接收在单个数据库事务内完成：任一份原件校验失败则整批回滚、不新增任何本地运行（已存在的本地运行保持原样）；全部通过才统一建立本地运行与目标行。并发重试由事务级咨询锁与内容指纹唯一索引收敛为同一批次，返回原本地编号。
