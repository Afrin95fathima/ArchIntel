import java.nio.file.Path;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.neo4j.dbms.api.DatabaseManagementService;
import org.neo4j.dbms.api.DatabaseManagementServiceBuilder;
import org.neo4j.configuration.GraphDatabaseSettings;
import org.neo4j.graphdb.*;

/** Reads only a job-owned jQAssistant store. Never loads customer classes. */
public final class ExportGraph {
    static List<String> ownedTypes;
    static List<Map<String,Object>> read(Transaction tx, String query, int limit) {
        List<Map<String,Object>> rows = new ArrayList<>();
        try (Result result = tx.execute(query, Map.of("limit", limit, "owned", ownedTypes))) {
            while (result.hasNext()) rows.add(result.next());
        }
        return rows;
    }

    public static void main(String[] args) throws Exception {
        ownedTypes = Arrays.asList(new ObjectMapper().readValue(Path.of(args[3]).toFile(), String[].class));
        DatabaseManagementService management = new DatabaseManagementServiceBuilder(Path.of(args[0]))
            .setConfig(GraphDatabaseSettings.pagecache_memory, 256L * 1024 * 1024).build();
        Map<String,Object> output = new LinkedHashMap<>();
        try (Transaction tx = management.database("neo4j").beginTx()) {
            output.put("classes", read(tx, """
                MATCH (t:Type:File) WHERE t.fqn IN $owned
                RETURN t.fqn AS fqn, labels(t) AS labels, properties(t) AS properties,
                  COUNT { (t)-[:DECLARES]->(:Method) } AS method_count,
                  COUNT { (t)-[:DECLARES]->(:Field) } AS field_count,
                  [(t)-[:ANNOTATED_BY]->()-[:OF_TYPE]->(a:Type) | a.fqn] AS annotations,
                  [(t)-[:DECLARES]->(m:Method) | {name: m.name, signature: m.signature,
                    annotations: [(m)-[:ANNOTATED_BY]->()-[:OF_TYPE]->(ma:Type) | ma.fqn]}] AS methods
                ORDER BY t.fqn LIMIT $limit
                """, Integer.parseInt(args[1]) + 1));
            Map<String,String> queries = new LinkedHashMap<>();
            queries.put("OTHER", "MATCH (s:Type:File)-[:DEPENDS_ON]->(t:Type)");
            queries.put("INHERITANCE", "MATCH (s:Type:File)-[:EXTENDS]->(t:Type)");
            queries.put("INTERFACE", "MATCH (s:Type:File)-[:IMPLEMENTS]->(t:Type)");
            queries.put("METHOD_CALL", "MATCH (s:Type:File)-[:DECLARES]->(:Method)-[:INVOKES]->(:Method)<-[:DECLARES]-(t:Type)");
            queries.put("FIELD_TYPE", "MATCH (s:Type:File)-[:DECLARES]->(:Field)-[:OF_TYPE]->(t:Type)");
            queries.put("ANNOTATION", "MATCH (s:Type:File)-[:ANNOTATED_BY]->()-[:OF_TYPE]->(t:Type)");
            queries.put("EXCEPTION", "MATCH (s:Type:File)-[:DECLARES]->(:Method)-[:THROWS|CATCHES]->(t:Type)");
            queries.put("GENERIC_TYPE", "MATCH (s:Type:File)-[:DECLARES*0..2]->(owner)-[:OF_GENERIC_TYPE|RETURNS_GENERIC|EXTENDS_GENERIC|IMPLEMENTS_GENERIC|DECLARES_TYPE_PARAMETER]->(b:Bound)-[:HAS_ACTUAL_TYPE_ARGUMENT|HAS_UPPER_BOUND|HAS_LOWER_BOUND|OF_COMPONENT_TYPE*0..6]->(bound:Bound)-[:OF_RAW_TYPE]->(t:Type)");
            List<Map<String,Object>> edges = new ArrayList<>();
            int maximum = Integer.parseInt(args[2]);
            for (var entry : queries.entrySet()) {
                var rows = read(tx, entry.getValue() + " WHERE s.fqn IN $owned RETURN DISTINCT s.fqn AS source, t.fqn AS target LIMIT $limit", maximum + 1);
                for (var row : rows) {
                    row.put("dependency_type", entry.getKey());
                    edges.add(row);
                    if (edges.size() > maximum) throw new IllegalArgumentException("Dependency limit exceeded");
                }
            }
            output.put("edges", edges);
            tx.commit();
        } finally {
            management.shutdown();
        }
        System.out.println("ARCHINTEL_GRAPH_JSON:" + new ObjectMapper().writeValueAsString(output));
    }
}
