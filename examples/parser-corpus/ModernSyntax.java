package example.parser;

import java.util.List;
import java.util.function.Function;

public class ModernSyntax {
    public String classify(int value) {
        return switch (value) {
            case 0 -> "zero";
            default -> "many";
        };
    }

    public List<String> normalize(List<String> values) {
        Function<String, String> trim = String::trim;
        return values.stream().map(trim).toList();
    }

    public Runnable callback() {
        return new Runnable() {
            @Override
            public void run() {
            }
        };
    }
}
