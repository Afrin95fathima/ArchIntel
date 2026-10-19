package com.fixture.edge.web;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import com.fixture.edge.model.OrderEntity;
import com.fixture.edge.model.OrderRepository;

@Controller
public class OrderAdminController {

	private final OrderRepository repository;

	public OrderAdminController(OrderRepository repository) {
		this.repository = repository;
	}

	@GetMapping("/admin/orders/latest")
	public String latest() {
		OrderEntity order = repository.latest();
		return order.getReference();
	}

}
