package com.fixture.edge.jobs;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.context.event.EventListener;
import org.springframework.jms.annotation.JmsListener;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class OrderEvents {

	@EventListener
	public void onStarted(String event) {
	}

	@KafkaListener(topics = "orders")
	public void consume(String payload) {
	}

	@JmsListener(destination = "billing.queue")
	public void billing(String payload) {
	}

	@RabbitListener(queues = { "audit" })
	public void audit(String payload) {
	}

}
