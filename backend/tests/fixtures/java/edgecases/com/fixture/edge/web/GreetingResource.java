package com.fixture.edge.web;

import javax.ws.rs.GET;
import javax.ws.rs.POST;
import javax.ws.rs.Path;

@Path("/jaxrs")
public class GreetingResource {

	@GET
	@Path("/hello")
	public String hello() {
		return "hello";
	}

	@POST
	public String post() {
		return "posted";
	}

}
