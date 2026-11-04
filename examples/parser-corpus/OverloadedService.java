package example.parser;

import java.util.List;
import java.util.Map;

public class OverloadedService {
    public String find(String id) {
        return id;
    }

    public String find(String id, Map<String, List<Long>> options) {
        return id + options.size();
    }

    public <T extends Number> List<T> convert(List<T> input) {
        return input;
    }

    static class NestedWorker {
        public void run() {
        }
    }
}
