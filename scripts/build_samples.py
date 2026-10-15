"""Build only repository-owned synthetic Java fixtures; never run their bytecode."""
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
JAVA = next((ROOT / '.runtime/java').glob('*')) / 'bin/javac.exe'
SOURCE = ROOT / 'samples/commerce/src'
CLASSES = ROOT / '.data/sample-classes'
SOURCE.mkdir(parents=True, exist_ok=True)
CLASSES.mkdir(parents=True, exist_ok=True)
files = {}

for package, names in {'org.springframework.stereotype': ['Service','Repository','Controller'], 'jakarta.persistence':['Entity']}.items():
    for name in names:
        files[package + '.' + name] = f'package {package}; @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME) public @interface {name} {{}}'

for domain in ['payment', 'orders', 'customer', 'inventory', 'reporting']:
    title = domain.title()
    package = f'com.northstar.{domain}'
    files[f'{package}.{title}Entity'] = f'package {package}; @jakarta.persistence.Entity public class {title}Entity {{ public String id; public String status; }}'
    files[f'{package}.{title}Repository'] = f'package {package}; @org.springframework.stereotype.Repository public class {title}Repository {{ public {title}Entity find() {{ return new {title}Entity(); }} }}'
    files[f'{package}.{title}Policy'] = f'package {package}; public interface {title}Policy {{ boolean valid({title}Entity entity); }}'
    files[f'{package}.{title}DefaultPolicy'] = f'package {package}; public class {title}DefaultPolicy implements {title}Policy {{ public boolean valid({title}Entity entity) {{ return entity != null; }} }}'
    files[f'{package}.{title}Controller'] = f'package {package}; @org.springframework.stereotype.Controller public class {title}Controller {{ private {title}Service service; public {title}Entity get() {{ return service.load(); }} }}'
    cross = {'payment':'com.northstar.orders.OrdersService', 'orders':'com.northstar.customer.CustomerService', 'customer':'com.northstar.payment.PaymentService'}.get(domain)
    extra = f'private {cross} partner; public Object related() {{ return partner.load(); }}' if cross else ''
    if domain in ['payment','customer','reporting']:
        extra += ' private com.northstar.shared.LedgerRepository ledger; public Object audit() { return ledger.find(); }'
    files[f'{package}.{title}Service'] = f'package {package}; @org.springframework.stereotype.Service public class {title}Service {{ private {title}Repository repository; private {title}Policy policy; public {title}Entity load() {{ return repository.find(); }} {extra} }}'
files['com.northstar.shared.LedgerEntity'] = 'package com.northstar.shared; @jakarta.persistence.Entity public class LedgerEntity { public String id; }'
files['com.northstar.shared.LedgerRepository'] = 'package com.northstar.shared; @org.springframework.stereotype.Repository public class LedgerRepository { public LedgerEntity find() { return new LedgerEntity(); } }'
files['com.northstar.notification.Message'] = 'package com.northstar.notification; public class Message { public String text; }'
files['com.northstar.notification.Template'] = 'package com.northstar.notification; public class Template { public Message render() { return new Message(); } }'
files['com.northstar.notification.Transport'] = 'package com.northstar.notification; public interface Transport { void send(Message m); }'
files['com.northstar.notification.EmailTransport'] = 'package com.northstar.notification; public class EmailTransport implements Transport { public void send(Message m) {} }'
files['com.northstar.notification.NotificationService'] = 'package com.northstar.notification; @org.springframework.stereotype.Service public class NotificationService { private Template template; private Transport transport; public void send() { transport.send(template.render()); } }'
fields = ''.join(f'private {fqn} field{i};' for i,fqn in enumerate(sorted(k for k in files if k.startswith('com.'))))
methods = ''.join(f'public int operation{i}() {{ return {i}; }}' for i in range(40))
files['com.northstar.orders.ApplicationCoordinator'] = f'package com.northstar.orders; public class ApplicationCoordinator {{ {fields} {methods} }}'
files['com.northstar.payment.PaymentRepository'] = 'package com.northstar.payment; @org.springframework.stereotype.Repository public class PaymentRepository { private java.util.List<PaymentEntity> cache; public PaymentEntity find() { return new PaymentEntity(); } public void validate() throws java.io.IOException { throw new java.io.IOException(); } }'
files['com.northstar.reporting.ReportFormatter'] = 'package com.northstar.reporting; public class ReportFormatter { private ReportTemplate template; public ReportTemplate template() { return template; } }'
files['com.northstar.reporting.ReportTemplate'] = 'package com.northstar.reporting; public class ReportTemplate { private ReportFormatter formatter; public ReportFormatter formatter() { return formatter; } }'

for fqn, content in files.items():
    path = SOURCE / (fqn.replace('.', '/') + '.java')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
sources = sorted(SOURCE.rglob('*.java'))
args = ROOT / '.data/javac-sources.txt'
args.write_text('\n'.join('"' + str(p).replace('\\','/') + '"' for p in sources), encoding='utf-8')
subprocess.run([str(JAVA), '--release', '17', '-g', '-d', str(CLASSES), '@' + str(args)], check=True)
for filename, prefix in [('northstar-commerce.jar',''),('northstar-commerce.war','WEB-INF/classes/'),('northstar-commerce-boot.jar','BOOT-INF/classes/')]:
    target = ROOT / 'samples' / filename
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nImplementation-Title: Synthetic Northstar Commerce\n')
        for cls in sorted(CLASSES.rglob('*.class')):
            if cls.relative_to(CLASSES).as_posix().startswith('com/'):
                archive.write(cls, prefix + cls.relative_to(CLASSES).as_posix())
    print(filename, target.stat().st_size)
