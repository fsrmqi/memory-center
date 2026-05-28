# Spring Cloud Indexing / Spring Cloud 索引说明

## 中文

Memory Center 第一版重点支持 Spring Cloud 多项目工作区。

### Feign 索引

扫描：

```java
@FeignClient(name = "article-service", path = "/article")
public interface ArticleFeignClient {
    @PostMapping("/move")
    Result moveArticle(@RequestBody MoveArticleRequest request);
}
```

生成：

```json
{
  "project": "common-api",
  "client": "ArticleFeignClient",
  "target_service": "article-service",
  "base_path": "/article",
  "methods": ["POST /move"]
}
```

### Controller 索引

扫描：

```java
@RestController
@RequestMapping("/article")
public class ArticleController {
    @PostMapping("/move")
    public String moveArticle() { return "ok"; }
}
```

生成 API endpoint 索引。

### MQ 索引

支持：

- `@KafkaListener(topics = "...")`
- `@RocketMQMessageListener(topic = "...", consumerGroup = "...")`

### 配置索引

支持：

- `application.yml`
- `application.yaml`
- `bootstrap.yml`
- `bootstrap.yaml`

重点提取 `spring.application.name` 等配置。

## English

The initial version indexes common Spring Cloud patterns: Feign clients, REST controllers, Kafka/RocketMQ listeners and YAML configuration files. The parser is intentionally lightweight and can be replaced by AST-based parsers in future versions.
