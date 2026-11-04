package com.example.task;

import com.example.api.MoveArticleRequest;

public interface ArticleAuditService {
    void recordMove(MoveArticleRequest request);
}
