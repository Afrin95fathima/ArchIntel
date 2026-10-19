"""Write minimal framework stubs so fixtures compile with genuine annotation descriptors and values.

Stubs are compiled to a separate directory and never included in fixture class output, so in analysis
they appear exactly like external library classes.
"""
from pathlib import Path
import sys

RT = '@java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME) '

ANNOTATIONS = {
    'org.springframework.stereotype': {'Controller': '', 'Service': '', 'Repository': '', 'Component': ''},
    'org.springframework.web.bind.annotation': {
        'RestController': '', 'ControllerAdvice': '', 'ResponseBody': '', 'RequestBody': '',
        'GetMapping': 'String[] value() default {}; String[] path() default {};',
        'PostMapping': 'String[] value() default {}; String[] path() default {};',
        'PutMapping': 'String[] value() default {}; String[] path() default {};',
        'DeleteMapping': 'String[] value() default {}; String[] path() default {};',
        'PatchMapping': 'String[] value() default {}; String[] path() default {};',
        'RequestMapping': 'String[] value() default {}; String[] path() default {}; RequestMethod[] method() default {};',
        'PathVariable': 'String value() default ""; String name() default ""; boolean required() default true;',
        'RequestParam': 'String value() default ""; String name() default ""; boolean required() default true; String defaultValue() default "";',
        'ModelAttribute': 'String value() default ""; String name() default "";',
        'InitBinder': 'String[] value() default {};',
        'ExceptionHandler': 'Class<?>[] value() default {};',
    },
    'org.springframework.data.jpa.repository': {'Query': 'String value() default "";'},
    'org.springframework.transaction.annotation': {'Transactional': 'boolean readOnly() default false;'},
    'org.springframework.cache.annotation': {'Cacheable': 'String[] value() default {};', 'EnableCaching': ''},
    'org.springframework.context.annotation': {'Configuration': 'boolean proxyBeanMethods() default true;', 'Bean': ''},
    'org.springframework.context.event': {'EventListener': ''},
    'org.springframework.boot.autoconfigure': {'SpringBootApplication': ''},
    'org.springframework.format.annotation': {'DateTimeFormat': 'String pattern() default "";'},
    'org.springframework.scheduling.annotation': {'Scheduled': 'String cron() default ""; long fixedRate() default -1;', 'EnableScheduling': ''},
    'org.springframework.kafka.annotation': {'KafkaListener': 'String[] topics() default {};'},
    'org.springframework.jms.annotation': {'JmsListener': 'String destination() default "";'},
    'org.springframework.amqp.rabbit.annotation': {'RabbitListener': 'String[] queues() default {};'},
    'jakarta.persistence': {
        'Entity': '', 'MappedSuperclass': '', 'Id': '', 'GeneratedValue': '', 'Table': 'String name() default "";',
        'Column': 'String name() default "";', 'OneToMany': 'String mappedBy() default "";', 'ManyToOne': '',
        'ManyToMany': '', 'JoinColumn': 'String name() default "";', 'JoinTable': 'String name() default "";',
        'OrderBy': 'String value() default "";'},
    'javax.persistence': {'Entity': '', 'Table': 'String name() default "";', 'Id': ''},
    'jakarta.validation': {'Valid': ''},
    'jakarta.validation.constraints': {'NotBlank': '', 'NotEmpty': '', 'Pattern': 'String regexp() default "";',
        'Digits': 'int integer() default 0; int fraction() default 0;', 'NotNull': '', 'Size': 'int min() default 0; int max() default 2147483647;'},
    'jakarta.xml.bind.annotation': {'XmlRootElement': '', 'XmlElement': ''},
    'jakarta.annotation': {'PostConstruct': ''},
    'javax.annotation': {'PostConstruct': ''},
    'javax.servlet.annotation': {'WebServlet': 'String[] value() default {};', 'WebFilter': 'String[] value() default {};'},
    'javax.ws.rs': {'GET': '', 'POST': '', 'Path': 'String value() default "";'},
}

TYPES = {
    'org/springframework/web/bind/annotation/RequestMethod.java':
        'package org.springframework.web.bind.annotation; public enum RequestMethod { GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS, TRACE }',
    'org/springframework/web/bind/WebDataBinder.java':
        'package org.springframework.web.bind; public class WebDataBinder { public void setDisallowedFields(String... f) {} '
        'public void setValidator(org.springframework.validation.Validator v) {} }',
    'org/springframework/ui/Model.java':
        'package org.springframework.ui; public interface Model { Model addAttribute(String name, Object value); }',
    'org/springframework/ui/ModelMap.java':
        'package org.springframework.ui; public class ModelMap extends java.util.LinkedHashMap<String,Object> { '
        'public ModelMap addAttribute(String n, Object v) { put(n, v); return this; } }',
    'org/springframework/validation/Errors.java':
        'package org.springframework.validation; public interface Errors { void rejectValue(String field, String code, String message); boolean hasErrors(); }',
    'org/springframework/validation/BindingResult.java':
        'package org.springframework.validation; public interface BindingResult extends Errors {}',
    'org/springframework/validation/Validator.java':
        'package org.springframework.validation; public interface Validator { boolean supports(Class<?> c); void validate(Object target, Errors errors); }',
    'org/springframework/web/servlet/mvc/support/RedirectAttributes.java':
        'package org.springframework.web.servlet.mvc.support; public interface RedirectAttributes { RedirectAttributes addFlashAttribute(String n, Object v); }',
    'org/springframework/web/servlet/ModelAndView.java':
        'package org.springframework.web.servlet; public class ModelAndView { public ModelAndView(String view) {} '
        'public ModelAndView addObject(Object o) { return this; } }',
    'org/springframework/data/repository/Repository.java':
        'package org.springframework.data.repository; public interface Repository<T, ID> {}',
    'org/springframework/data/jpa/repository/JpaRepository.java':
        'package org.springframework.data.jpa.repository; public interface JpaRepository<T, ID> extends org.springframework.data.repository.Repository<T, ID> { '
        'java.util.Optional<T> findById(ID id); <S extends T> S save(S entity); java.util.List<T> findAll(); }',
    'org/springframework/data/domain/Pageable.java': 'package org.springframework.data.domain; public interface Pageable {}',
    'org/springframework/data/domain/Page.java':
        'package org.springframework.data.domain; public interface Page<T> { java.util.List<T> getContent(); int getTotalPages(); long getTotalElements(); }',
    'org/springframework/data/domain/PageRequest.java':
        'package org.springframework.data.domain; public class PageRequest implements Pageable { public static PageRequest of(int p, int s) { return new PageRequest(); } }',
    'org/springframework/boot/SpringApplication.java':
        'package org.springframework.boot; public class SpringApplication { public static Object run(Class<?> c, String... args) { return null; } }',
    'org/springframework/format/Formatter.java':
        'package org.springframework.format; public interface Formatter<T> { String print(T value, java.util.Locale l); '
        'T parse(String text, java.util.Locale l) throws java.text.ParseException; }',
    'org/springframework/util/StringUtils.java':
        'package org.springframework.util; public abstract class StringUtils { public static boolean hasText(String s) { return s != null && !s.isBlank(); } '
        'public static boolean hasLength(String s) { return s != null && !s.isEmpty(); } }',
    'org/springframework/web/servlet/config/annotation/InterceptorRegistry.java':
        'package org.springframework.web.servlet.config.annotation; public class InterceptorRegistry { public void addInterceptor(Object o) {} }',
    'org/springframework/web/servlet/config/annotation/WebMvcConfigurer.java':
        'package org.springframework.web.servlet.config.annotation; public interface WebMvcConfigurer { default void addInterceptors(InterceptorRegistry r) {} }',
    'javax/servlet/http/HttpServletRequest.java': 'package javax.servlet.http; public interface HttpServletRequest { String getParameter(String n); }',
    'javax/servlet/http/HttpServletResponse.java': 'package javax.servlet.http; public interface HttpServletResponse { void setStatus(int s); }',
    'javax/servlet/http/HttpServlet.java':
        'package javax.servlet.http; public abstract class HttpServlet { protected void doGet(HttpServletRequest q, HttpServletResponse r) {} '
        'protected void doPost(HttpServletRequest q, HttpServletResponse r) {} }',
    'javax/servlet/ServletRequest.java': 'package javax.servlet; public interface ServletRequest {}',
    'javax/servlet/ServletResponse.java': 'package javax.servlet; public interface ServletResponse {}',
    'javax/servlet/FilterChain.java': 'package javax.servlet; public interface FilterChain { void doFilter(ServletRequest q, ServletResponse r); }',
    'javax/servlet/Filter.java': 'package javax.servlet; public interface Filter { void doFilter(ServletRequest q, ServletResponse r, FilterChain c); }',
    'javax/xml/bind/JAXBContext.java':
        'package javax.xml.bind; public abstract class JAXBContext { public static JAXBContext newInstance(Class<?>... c) { return null; } }',
    'org/apache/log4j/Logger.java':
        'package org.apache.log4j; public class Logger { public static Logger getLogger(Class<?> c) { return new Logger(); } public void info(Object m) {} public void error(Object m) {} }',
    'org/apache/commons/lang/StringUtils.java':
        'package org.apache.commons.lang; public class StringUtils { public static boolean isBlank(String s) { return s == null || s.trim().isEmpty(); } }',
    'org/apache/struts/action/Action.java':
        'package org.apache.struts.action; public class Action { public Object execute(Object mapping, Object form) { return null; } }',
}


def write(root: Path) -> list[Path]:
    paths = []
    for package, items in ANNOTATIONS.items():
        for name, body in items.items():
            path = root / package.replace('.', '/') / (name + '.java')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'package {package}; {RT}public @interface {name} {{ {body} }}\n', encoding='utf-8')
            paths.append(path)
    for relative, source in TYPES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source + '\n', encoding='utf-8')
        paths.append(path)
    return paths


if __name__ == '__main__':
    for item in write(Path(sys.argv[1])):
        print(item)
