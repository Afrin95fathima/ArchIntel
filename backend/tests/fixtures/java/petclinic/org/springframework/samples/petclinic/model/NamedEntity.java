package org.springframework.samples.petclinic.model;

import jakarta.persistence.Column;
import jakarta.persistence.MappedSuperclass;
import jakarta.validation.constraints.NotBlank;

@MappedSuperclass
public class NamedEntity extends BaseEntity {

	@Column(name = "name")
	@NotBlank
	private String name;

	public String getName() {
		return this.name;
	}

	public void setName(String name) {
		this.name = name;
	}

	@Override
	public String toString() {
		return this.getName();
	}

}
