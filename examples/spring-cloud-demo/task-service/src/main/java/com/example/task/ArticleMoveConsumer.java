package com.example.task;

import org.springframework.kafka.annotation.KafkaListener;

public class ArticleMoveConsumer {
    @KafkaListener(topics = "article-pubtime-change", groupId = "article-move")
    public void consume(String body) {}
}
