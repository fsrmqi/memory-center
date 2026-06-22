package example.parser;

import lombok.RequiredArgsConstructor;

@RequiredArgsConstructor
public class ConstructorInjectedService {
    private final ArticleRepository articleRepository;
    private final AuditClient auditClient;

    public void execute(String id) {
        articleRepository.load(id);
        auditClient.record(id);
    }
}
