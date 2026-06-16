package com.example.article;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/article")
public class ArticleController {
    private final ArticleWorkflowService articleWorkflowService;

    public ArticleController(ArticleWorkflowService articleWorkflowService) {
        this.articleWorkflowService = articleWorkflowService;
    }

    @PostMapping("/move")
    public String moveArticle() {
        return articleWorkflowService.moveArticle();
    }
}
