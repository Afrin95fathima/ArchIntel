package org.springframework.samples.petclinic.system;

import org.springframework.cache.annotation.EnableCaching;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableCaching
class CacheConfiguration {

	@Bean
	public Runnable petclinicCacheConfigurationCustomizer() {
		return () -> cacheConfiguration();
	}

	private String cacheConfiguration() {
		return "vets";
	}

}
