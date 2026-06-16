package com.example.article;

import org.springframework.stereotype.Service;

@Service
public class ArticleWorkflowServiceImpl implements ArticleWorkflowService {
    @Override
    public String moveArticle() {
        return "ok";
    }
}
