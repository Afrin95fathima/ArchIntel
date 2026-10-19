package com.fixture.edge.cycle.a;

import java.util.List;

public class Customer {

	private List<Order> orders;

	public int orderCount() {
		return orders.size();
	}

	public Address address() {
		return new Address();
	}

}
