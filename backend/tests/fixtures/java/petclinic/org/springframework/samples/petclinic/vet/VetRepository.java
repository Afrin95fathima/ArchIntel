package org.springframework.samples.petclinic.vet;

import java.util.Collection;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.repository.Repository;
import org.springframework.transaction.annotation.Transactional;

public interface VetRepository extends Repository<Vet, Integer> {

	@Transactional(readOnly = true)
	@Cacheable("vets")
	Collection<Vet> findAll();

	@Transactional(readOnly = true)
	@Cacheable("vets")
	Page<Vet> findAll(Pageable pageable);

}
