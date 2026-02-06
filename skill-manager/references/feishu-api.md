# 飞书多维表格 API 参考

## 认证

```
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Body: {"app_id": "xxx", "app_secret": "xxx"}
Response: {"code": 0, "tenant_access_token": "t-xxx", "expire": 7200}
```

## 创建多维表格

```
POST https://open.feishu.cn/open-apis/bitable/v1/apps
Headers: Authorization: Bearer <token>, Content-Type: application/json
Body: {"name": "表格名称"}
Response: {"code": 0, "data": {"app": {"app_token": "bascnXXX", "name": "...", "url": "..."}}}
```

## 创建数据表

```
POST https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables
Body: {
  "table": {
    "name": "表名",
    "default_view_name": "默认视图",
    "fields": [
      {"field_name": "列名", "type": 1}
    ]
  }
}
Response: {"code": 0, "data": {"table_id": "tblXXX"}}
```

字段类型: 1=文本, 2=数字, 5=日期, 15=URL

## 记录操作

批量创建:
```
POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create
Body: {"records": [{"fields": {"列名": "值"}}, ...]}
```

更新:
```
PUT /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}
Body: {"fields": {"列名": "新值"}}
```

查询:
```
GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=500
Response: {"data": {"items": [{"record_id": "recXXX", "fields": {...}}], "has_more": bool, "page_token": "..."}}
```

删除:
```
DELETE /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}
```

## URL 字段值格式

```json
{"text": "显示文本", "link": "https://example.com"}
```

## 常见错误码

- 99991663: token 无效或过期
- 1254043: 表不存在
- 1254004: app_token 无效
- 1254023: 无权限
