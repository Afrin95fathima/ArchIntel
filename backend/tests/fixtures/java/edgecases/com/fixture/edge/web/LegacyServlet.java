package com.fixture.edge.web;

import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

@WebServlet("/legacy/report")
public class LegacyServlet extends HttpServlet {

	@Override
	protected void doGet(HttpServletRequest request, HttpServletResponse response) {
		response.setStatus(200);
	}

	@Override
	protected void doPost(HttpServletRequest request, HttpServletResponse response) {
		response.setStatus(201);
	}

}
