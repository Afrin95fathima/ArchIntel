package com.fixture.edge.jobs;

public class CliTool {

	public static void main(String[] args) {
		Runnable task = () -> System.out.println(args.length);
		task.run();
	}

}
