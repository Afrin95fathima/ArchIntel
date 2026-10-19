package com.fixture.edge.jobs;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import jakarta.annotation.PostConstruct;

@Component
public class ReminderJob {

	private boolean ready;

	@PostConstruct
	public void init() {
		ready = true;
	}

	@Scheduled(cron = "0 0 * * * *")
	public void sendReminders() {
		if (ready) {
			System.out.println("reminders");
		}
	}

}
