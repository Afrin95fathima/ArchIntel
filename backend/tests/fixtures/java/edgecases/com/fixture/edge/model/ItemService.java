package com.fixture.edge.model;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class ItemService {

	private static final List<Item> CACHE = new ArrayList<>();

	private static int counter;

	public Item find(long id) {
		return CACHE.isEmpty() ? null : CACHE.get(0);
	}

	public Item save(Item item) {
		counter++;
		CACHE.add(item);
		return item;
	}

	public List<Item> search(String query) {
		List<Item> result = new ArrayList<>(CACHE);
		result.sort(new NameOrder());
		return result;
	}

	public void delete(long id) {
		CACHE.removeIf(item -> item.getId() == id);
	}

	public int calculate(int value) {
		return value * 2;
	}

	public int calculate(String value) {
		return value.length();
	}

	public int calculate(int left, int right) {
		return left + right;
	}

	static class NameOrder implements Comparator<Item> {

		@Override
		public int compare(Item left, Item right) {
			return left.getName().compareTo(right.getName());
		}

	}

	class Tracker {

		int seen() {
			return counter;
		}

	}

	public Runnable anonymous() {
		return new Runnable() {
			@Override
			public void run() {
				calculate(1);
			}
		};
	}

}
