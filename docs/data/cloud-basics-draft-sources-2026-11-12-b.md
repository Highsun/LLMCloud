# 120条候选语料的公开来源索引（B）

日期：2026-11-13。此索引只公开30个问答族的主题、来源URL和草稿哈希，不含训练/验证/测试正文。完整语料仍为draft_unreviewed，人工审核0/120。

原资料于2026-11-12逐页打开核对，答案采用原创中文表述。来源可查不等于已完成事实、措辞、来源使用和语义独立性的人工作业。继承的5个旧来源ID仅用于冻结协议校验，不在下表重复计数。

| 问答族 | 主题 | 事实参考来源 | 条数 |
| --- | --- | --- | --- |
| `docker-volume-lifecycle` | Docker 数据卷生命周期 | [Docker volumes](https://docs.docker.com/engine/storage/volumes/) | 4 |
| `docker-bind-mount-semantics` | 绑定挂载与宿主路径 | [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/) | 4 |
| `docker-tmpfs-temporary-data` | tmpfs 临时数据 | [Docker tmpfs mounts](https://docs.docker.com/engine/storage/tmpfs/) | 4 |
| `docker-multistage-artifacts` | 多阶段构建 | [Docker multi-stage builds](https://docs.docker.com/build/building/multi-stage/) | 4 |
| `docker-build-cache-rules` | 构建缓存失效 | [Docker build cache invalidation](https://docs.docker.com/build/cache/invalidation/) | 4 |
| `docker-build-context-filter` | 构建上下文与忽略文件 | [Docker build context](https://docs.docker.com/build/concepts/context/) | 4 |
| `docker-image-digest-pinning` | 镜像标签与摘要 | [Docker image pull by tag or digest](https://docs.docker.com/reference/cli/docker/image/pull/) | 4 |
| `docker-resource-constraints` | 容器资源限制 | [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/) | 4 |
| `docker-published-port-mapping` | 容器端口发布 | [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/) | 4 |
| `docker-network-service-discovery` | 容器网络与服务发现 | [Docker networking overview](https://docs.docker.com/engine/network/) | 4 |
| `docker-restart-policy` | 容器重启策略 | [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/) | 4 |
| `docker-stdout-log-collection` | 容器日志输出 | [Docker container logs](https://docs.docker.com/engine/logging/) | 4 |
| `http-etag-conditional-access` | ETag 与条件请求 | [MDN ETag](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/ETag) | 4 |
| `http-byte-range-download` | HTTP 范围下载 | [MDN HTTP range requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Range_requests) | 4 |
| `http-cache-control-policy` | HTTP 缓存策略 | [MDN Cache-Control](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control) | 4 |
| `http-content-encoding-type` | 媒体类型与内容编码 | [MDN Content-Encoding](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Encoding) | 4 |
| `http-authentication-permission` | HTTP 身份与权限反馈 | [MDN HTTP authentication](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Authentication) | 4 |
| `dns-record-value-types` | DNS 记录类型 | [Route 53 DNS record types](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/ResourceRecordTypes.html) | 4 |
| `dns-ttl-cache-expiry` | DNS TTL 与缓存 | [Route 53 simple-record TTL](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resource-record-sets-values-basic.html) | 4 |
| `sqlite-transaction-atomicity` | SQLite 事务边界 | [SQLite transaction control](https://www.sqlite.org/lang_transaction.html) | 4 |
| `sqlite-connection-isolation` | SQLite 连接隔离 | [SQLite isolation](https://www.sqlite.org/isolation.html) | 4 |
| `sqlite-consistent-backup` | SQLite 一致性备份 | [SQLite online backup](https://www.sqlite.org/backup.html) | 4 |
| `sqlite-constraint-null-rules` | SQLite 约束与空值 | [SQLite table constraints](https://www.sqlite.org/lang_createtable.html) | 4 |
| `sqlite-query-index-planning` | SQLite 查询索引 | [SQLite query planning](https://www.sqlite.org/queryplanner.html) | 4 |
| `s3-object-key-namespace` | S3 对象键命名 | [Amazon S3 object keys](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html) | 4 |
| `s3-versioned-object-history` | S3 对象版本 | [Amazon S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html) | 4 |
| `s3-multipart-upload-process` | S3 分段上传 | [Amazon S3 multipart upload](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html) | 4 |
| `s3-object-checksum-validation` | 对象校验和与完整性 | [Amazon S3 object integrity](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html) | 4 |
| `s3-object-lifecycle-rules` | S3 生命周期规则 | [Amazon S3 Lifecycle](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html) | 4 |
| `load-balancer-listener-target` | 负载均衡监听器与目标 | [Elastic Load Balancing listeners and targets](https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/how-elastic-load-balancing-works.html) | 4 |

合计120条/30族，按原工具seed42划分为96/12/12条；同族不跨集。仅通过精确匹配/保留族检查，语义近重复仍待双人审核。

原JSONL SHA-256：`d8a00d7bd16354a0577b6aeef88437c30a633c37e02a958d59d649e83d227f1e`；build_id=`54acf9229ff98c04`。

[语料交接说明](cloud-basics-draft-2026-11-12-b.md) · [本次发布总览](../testing/laptop-3060-handoff-2026-11-13.md)
