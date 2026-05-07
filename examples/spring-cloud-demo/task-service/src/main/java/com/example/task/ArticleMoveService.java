package com.example.task;

import com.example.api.ArticleFeignClient;
import com.example.api.MoveArticleRequest;
import org.springframework.stereotype.Service;

@Service
public class ArticleMoveService {
    private final ArticleFeignClient articleFeignClient;

    public ArticleMoveService(ArticleFeignClient articleFeignClient) {
        this.articleFeignClient = articleFeignClient;
    }

    public void move(MoveArticleRequest request) {
        request.getUrlmd5();
        articleFeignClient.moveArticle(request);
    }
}
