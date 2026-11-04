package example.parser;

import java.util.List;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/generic")
public class GenericController<T> {
    @RequestMapping(value = "/items", method = RequestMethod.POST)
    public List<T> save(List<T> items) {
        return items;
    }
}
