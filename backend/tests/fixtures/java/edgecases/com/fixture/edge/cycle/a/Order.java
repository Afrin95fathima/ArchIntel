package com.fixture.edge.cycle.a;

import com.fixture.edge.cycle.b.Invoice;

public class Order {

	private Customer customer;

	public Customer getCustomer() {
		return customer;
	}

	public Invoice invoice() {
		return new Invoice(this);
	}

	public Order self() {
		return this.next();
	}

	private Order next() {
		return this;
	}

}
