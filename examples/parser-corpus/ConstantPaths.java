package example.parser;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

interface RouteConstants {
    String BASE = "/catalog";
    String ITEM = "/{id}";
    String SERVICE = "catalog-service";
}

@RestController
@RequestMapping(RouteConstants.BASE)
class ConstantController {
    @GetMapping(RouteConstants.ITEM)
    public String getById(String id) {
        return id;
    }
}

@FeignClient(name = RouteConstants.SERVICE, path = RouteConstants.BASE)
interface ConstantClient {
    @GetMapping(RouteConstants.ITEM)
    String getById(String id);
}
