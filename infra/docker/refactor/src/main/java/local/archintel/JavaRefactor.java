package local.archintel;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Modifier;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.printer.lexicalpreservation.LexicalPreservingPrinter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public final class JavaRefactor {
    private static void fail(String code) { System.err.println(code); System.exit(2); }

    public static void main(String[] args) throws Exception {
        if (args.length != 5 || !args[0].equals("INTRODUCE_INTERFACE")) fail("INVALID_RECIPE_ARGUMENTS");
        Path input = Path.of(args[1]).normalize();
        Path modifiedOutput = Path.of(args[2]).normalize();
        Path interfaceOutput = Path.of(args[3]).normalize();
        String interfaceName = args[4];
        if (!interfaceName.matches("[A-Z][A-Za-z0-9_]{0,79}")) fail("INVALID_INTERFACE_NAME");
        String requested = System.getenv("ARCHINTEL_RECIPE_METHODS");
        if (requested == null || requested.isBlank()) fail("METHODS_REQUIRED");
        Set<String> methods = new LinkedHashSet<>(Arrays.asList(requested.split(",", -1)));
        if (methods.isEmpty() || methods.size() > 20 || methods.stream().anyMatch(n -> !n.matches("[A-Za-z_$][A-Za-z0-9_$]{0,79}"))) fail("INVALID_METHODS");

        ParserConfiguration configuration = new ParserConfiguration().setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        ParseResult<CompilationUnit> parsed = new JavaParser(configuration).parse(input);
        if (!parsed.isSuccessful() || parsed.getResult().isEmpty()) fail("JAVA_PARSE_FAILED");
        CompilationUnit unit = parsed.getResult().get();
        LexicalPreservingPrinter.setup(unit);
        List<ClassOrInterfaceDeclaration> classes = unit.findAll(ClassOrInterfaceDeclaration.class).stream()
            .filter(c -> !c.isInterface() && c.getParentNode().orElse(null) == unit).toList();
        if (classes.size() != 1) fail("ONE_TOP_LEVEL_CLASS_REQUIRED");
        ClassOrInterfaceDeclaration implementation = classes.get(0);
        if (implementation.getNameAsString().equals(interfaceName) || unit.getInterfaceByName(interfaceName).isPresent()) fail("INTERFACE_ALREADY_EXISTS");
        // This recipe deliberately avoids type resolution. Reject signatures whose
        // meaning depends on the implementation's lexical scope.
        if (unit.getTypes().size() != 1 || !implementation.getTypeParameters().isEmpty()
                || implementation.getMembers().stream().anyMatch(m -> m.isTypeDeclaration())) fail("UNSUPPORTED_TYPE_SCOPE");
        if (implementation.getImplementedTypes().stream().anyMatch(t -> t.getNameAsString().equals(interfaceName))
                || unit.getImports().stream().anyMatch(i -> i.isStatic()
                    || (!i.isAsterisk() && i.getName().getIdentifier().equals(interfaceName)))) fail("INTERFACE_NAME_OR_IMPORT_CONFLICT");

        CompilationUnit contract = new CompilationUnit();
        unit.getPackageDeclaration().ifPresent(p -> contract.setPackageDeclaration(p.getNameAsString()));
        unit.getImports().forEach(i -> contract.addImport(i.clone()));
        ClassOrInterfaceDeclaration declaration = contract.addInterface(interfaceName).setPublic(true);
        for (String methodName : methods) {
            List<MethodDeclaration> matches = implementation.getMethodsByName(methodName);
            if (matches.size() != 1) fail("METHOD_MISSING_OR_OVERLOADED:" + methodName);
            if (!matches.get(0).isPublic() || matches.get(0).isStatic()
                    || matches.get(0).getReceiverParameter().isPresent()) fail("UNSUPPORTED_METHOD_SIGNATURE");
            MethodDeclaration signature = matches.get(0).clone();
            signature.removeBody();
            signature.getAnnotations().clear();
            signature.setModifiers(Modifier.Keyword.PUBLIC);
            declaration.addMember(signature);
        }
        implementation.addImplementedType(interfaceName);
        Files.createDirectories(modifiedOutput.getParent());
        Files.createDirectories(interfaceOutput.getParent());
        Files.writeString(modifiedOutput, LexicalPreservingPrinter.print(unit), StandardCharsets.UTF_8);
        Files.writeString(interfaceOutput, contract.toString(), StandardCharsets.UTF_8);
    }
}
