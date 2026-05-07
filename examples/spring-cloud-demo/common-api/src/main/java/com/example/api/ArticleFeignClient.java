package com.example.api;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "article-service", path = "/article")
public interface ArticleFeignClient {
    @PostMapping("/move")
    Result moveArticle(@RequestBody MoveArticleRequest request);
}
