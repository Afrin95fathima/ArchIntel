package local.archintel;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;
class AppTest {
    @Test void preservesValue() { assertEquals(1, new App().value()); }
}
