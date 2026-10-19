package com.fixture.edge.model;

import org.springframework.stereotype.Repository;

@Repository
public class OrderRepository {

	public OrderEntity latest() {
		return new OrderEntity();
	}

}
