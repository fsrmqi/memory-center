package com.example.task;

import com.example.api.MoveArticleRequest;
import org.springframework.stereotype.Service;

@Service
public class ArticleAuditServiceImpl implements ArticleAuditService {
    @Override
    public void recordMove(MoveArticleRequest request) {
        request.getUrlmd5();
    }
}
