package com.fixture.edge.cycle.b;

import com.fixture.edge.cycle.a.Order;

public class Invoice {

	private final Order order;

	public Invoice(Order order) {
		this.order = order;
	}

	public Order order() {
		return order;
	}

}
