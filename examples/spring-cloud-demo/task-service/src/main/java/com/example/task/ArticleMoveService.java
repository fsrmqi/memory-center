package com.example.task;

import com.example.api.ArticleFeignClient;
import com.example.api.MoveArticleRequest;
import org.springframework.stereotype.Service;

@Service
public class ArticleMoveService {
    private final ArticleFeignClient articleFeignClient;
    private final ArticleAuditService articleAuditService;

    public ArticleMoveService(ArticleFeignClient articleFeignClient, ArticleAuditService articleAuditService) {
        this.articleFeignClient = articleFeignClient;
        this.articleAuditService = articleAuditService;
    }

    public void move(MoveArticleRequest request) {
        request.getUrlmd5();
        validateMove(request);
        articleAuditService.recordMove(request);
        articleFeignClient.moveArticle(request);
    }

    private void validateMove(MoveArticleRequest request) {
        request.getUrlmd5();
    }
}
