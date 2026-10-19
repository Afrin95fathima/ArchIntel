package com.fixture.edge.legacy;

import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "billing")
public class BillingRecord {

	@Id
	private Long id;

	public void touch(BillingAction action) {
		action.oldApi();
	}

}
