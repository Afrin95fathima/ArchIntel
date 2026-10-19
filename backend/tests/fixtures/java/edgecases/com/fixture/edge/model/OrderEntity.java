package com.fixture.edge.model;

import jakarta.persistence.Entity;

@Entity
public class OrderEntity {

	private String reference;

	public String getReference() {
		return reference;
	}

}
