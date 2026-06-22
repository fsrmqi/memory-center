package example.parser;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;

interface BaseContract {
    default String normalize(String value) {
        return value.trim();
    }
}

@FeignClient(name = "article-service", path = "/articles", fallback = ContractFallback.class)
public interface ContractApi extends BaseContract {
    @RequestMapping(value = "/{id}", method = RequestMethod.GET)
    String getById(String id);
}

class ContractFallback implements ContractApi {
    public String getById(String id) {
        return "missing";
    }
}
