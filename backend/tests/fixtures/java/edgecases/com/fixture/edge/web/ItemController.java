package com.fixture.edge.web;

import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.fixture.edge.model.Item;
import com.fixture.edge.model.ItemService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

@RestController
@RequestMapping("/api/items")
public class ItemController {

	private final ItemService service;

	public ItemController(ItemService service) {
		this.service = service;
	}

	@GetMapping("/{id}")
	public Item get(@PathVariable("id") long id) {
		return service.find(id);
	}

	@PostMapping
	public Item create(@Valid @RequestBody Item item) {
		return service.save(item);
	}

	@RequestMapping(value = "/search", method = RequestMethod.GET)
	public List<Item> search(@RequestParam("q") @NotNull @Size(min = 2, max = 40) String query) {
		return service.search(query);
	}

	@RequestMapping(path = "/bulk", method = { RequestMethod.PUT, RequestMethod.PATCH })
	public int bulk(@RequestBody List<Item> items) {
		return items.size();
	}

	@DeleteMapping({ "/{id}", "/remove/{id}" })
	public void delete(@PathVariable long id) {
		service.delete(id);
	}

	@RequestMapping("/legacy-any")
	public String any() {
		return "any";
	}

	public String notAnEndpoint() {
		return "helper";
	}

}
