package com.fixture.edge.legacy;

import javax.xml.bind.JAXBContext;
import org.apache.commons.lang.StringUtils;
import org.apache.log4j.Logger;
import org.apache.struts.action.Action;

public class BillingAction extends Action {

	private static final Logger LOG = Logger.getLogger(BillingAction.class);

	@Override
	public Object execute(Object mapping, Object form) {
		LOG.info("billing");
		if (StringUtils.isBlank(String.valueOf(form))) {
			return null;
		}
		return JAXBContext.newInstance(BillingRecord.class);
	}

	@Deprecated
	public void oldApi() {
	}

}
