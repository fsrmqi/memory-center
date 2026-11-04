package com.example.task;

import com.example.api.ArticleFeignClient;
import com.example.api.MoveArticleRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class ArticleMoveConsumer {
    private final ArticleMoveService articleMoveService;

    @Value("${article.move.topic}")
    private String topic;

    public ArticleMoveConsumer(ArticleMoveService articleMoveService) {
        this.articleMoveService = articleMoveService;
    }

    @KafkaListener(topics = "article-pubtime-change", groupId = "article-move")
    public void consume(MoveArticleRequest message) {
        message.getOldPubTime();
        message.getNewPubTime();
        articleMoveService.move(message);
    }
}
