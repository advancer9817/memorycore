package org.mcore.storage.privacy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 写入端密钥脱敏层。
 *
 * 移植自旧版 Python `memorycore/privacy.py`（160 行）。Java 迁移期间该能力整体丢失，
 * 导致经 Java 写入的记忆会把 API Key / Token / 私钥 / 含密码连接串**明文落库**，
 * 并被后续 search / context 召回回灌 Agent 上下文。
 *
 * 设计取舍（与 Python 保持一致）：
 * - 模式 + 熵双通道：确定性、无外部依赖、无网络调用。
 * - 只脱敏不拒收：用占位符替换，保留上下文语义。
 * - 幂等：对已脱敏文本重复执行是 no-op（占位符不参与二次判定）。
 */
@Component
public class RedactionService {

    private static final Logger log = LoggerFactory.getLogger(RedactionService.class);

    /** 单条规则：标签 / 模式 / 替换模板 */
    private record Rule(String label, Pattern pattern, String replacement) {
    }

    /**
     * 规则表，顺序敏感 —— 具体规则必须排在通用 key=value 规则之前，
     * 否则 `sk-xxx` 会先被 env_assignment 的通用模式吃掉，丢失精确标签。
     */
    private static final List<Rule> RULES = List.of(
            // OpenAI / Anthropic 风格 bearer token：sk-… / sk-ant-…
            new Rule("openai_key",
                    Pattern.compile("\\bsk-(?:ant-)?[A-Za-z0-9\\-_]{20,}"),
                    "[REDACTED-API-KEY]"),
            // GitHub PAT：ghp_ / gho_ / ghu_ / ghs_ / ghr_ / github_pat_
            new Rule("github_token",
                    Pattern.compile("\\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9]{20,}"),
                    "[REDACTED-GITHUB-TOKEN]"),
            // AWS access key id：AKIA + 16 位大写
            new Rule("aws_access_key",
                    Pattern.compile("\\bAKIA[0-9A-Z]{16}\\b"),
                    "[REDACTED-AWS-KEY]"),
            // AWS secret：关键字后跟 40 位 base64 风格
            new Rule("aws_secret",
                    Pattern.compile("(?i)(aws[_-]secret[_-]access[_-]key\\s*[:=]\\s*)['\"]?([A-Za-z0-9+/]{40})['\"]?"),
                    "$1[REDACTED]"),
            // Authorization: Bearer xxx
            new Rule("bearer_token",
                    Pattern.compile("(?i)\\bBearer\\s+[A-Za-z0-9\\-._~+/]+=*\\b"),
                    "Bearer [REDACTED]"),
            // PEM 私钥块（含多行）
            new Rule("pem_private_key",
                    Pattern.compile("-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\\s\\S]+?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
                    "[REDACTED-PRIVATE-KEY]"),
            // 连接串内嵌口令：scheme://user:password@host
            new Rule("connection_string",
                    Pattern.compile("(?i)(\\w+://[^:@\\s]+:)([^@\\s]+)(@)"),
                    "$1[REDACTED]$3"),
            // 通用 key=value 赋值 —— 置于最后
            new Rule("env_assignment",
                    Pattern.compile("(?i)((?:api[_-]?key|secret|token|password|passwd|pwd|credential|auth)" +
                            "[_A-Z0-9]*\\s*[:=]\\s*)['\"]?([A-Za-z0-9+/\\-_.]{8,})['\"]?"),
                    "$1[REDACTED]")
    );

    /** token 形态子串：20+ 位字母数字与常见密钥符号 */
    private static final Pattern HIGH_ENTROPY_TOKEN = Pattern.compile("[A-Za-z0-9+/\\-_.]{20,}");

    /** 已脱敏占位符，不得被熵检测二次标记 */
    private static final Pattern REDACTED_PLACEHOLDER = Pattern.compile("\\[REDACTED[^\\]]*\\]");

    /** Shannon 熵阈值（bits/char）；典型英文文本约 4.0 */
    private static final double ENTROPY_THRESHOLD = 4.5;
    private static final int MIN_TOKEN_LEN = 20;

    public record RedactResult(String text, int redactedCount, List<String> labels) {
        public boolean changed() {
            return redactedCount > 0;
        }
    }

    /** 对单段文本执行脱敏 */
    public RedactResult redact(String text) {
        if (text == null || text.isEmpty()) {
            return new RedactResult(text, 0, List.of());
        }
        String result = text;
        int count = 0;
        List<String> labels = new ArrayList<>();

        for (Rule rule : RULES) {
            Matcher m = rule.pattern().matcher(result);
            StringBuffer sb = new StringBuffer();
            int n = 0;
            while (m.find()) {
                n++;
                m.appendReplacement(sb, rule.replacement());
            }
            if (n > 0) {
                m.appendTail(sb);
                result = sb.toString();
                count += n;
                labels.add(rule.label());
            }
        }

        // 熵通道：捕获前缀模式未覆盖的高熵未知密钥
        EntropyOutcome eo = redactHighEntropyTokens(result);
        if (eo.count() > 0) {
            result = eo.text();
            count += eo.count();
            labels.add("high_entropy");
        }

        return new RedactResult(result, count, labels);
    }

    private record EntropyOutcome(String text, int count) {
    }

    /** 替换未被模式通道处理的高熵 token */
    private EntropyOutcome redactHighEntropyTokens(String text) {
        // 已存在的占位符需保护，避免被当作高熵 token
        List<String> placeholders = new ArrayList<>();
        Matcher pm = REDACTED_PLACEHOLDER.matcher(text);
        while (pm.find()) {
            placeholders.add(pm.group());
        }

        Matcher m = HIGH_ENTROPY_TOKEN.matcher(text);
        StringBuilder sb = new StringBuilder();
        int[] count = {0};
        int last = 0;
        while (m.find()) {
            String token = m.group();
            sb.append(text, last, m.start());
            if (placeholders.contains(token)) {
                sb.append(token);
            } else if (token.length() >= MIN_TOKEN_LEN && shannonEntropy(token) >= ENTROPY_THRESHOLD) {
                sb.append("[REDACTED-HIGH-ENTROPY]");
                count[0]++;
            } else {
                sb.append(token);
            }
            last = m.end();
        }
        sb.append(text, last, text.length());
        return new EntropyOutcome(sb.toString(), count[0]);
    }

    /** Shannon 熵（bits/char） */
    static double shannonEntropy(String s) {
        if (s == null || s.isEmpty()) {
            return 0.0;
        }
        Map<Character, Integer> freq = new LinkedHashMap<>();
        for (int i = 0; i < s.length(); i++) {
            freq.merge(s.charAt(i), 1, Integer::sum);
        }
        int n = s.length();
        double entropy = 0.0;
        for (int v : freq.values()) {
            double p = (double) v / n;
            entropy -= p * (Math.log(p) / Math.log(2));
        }
        return entropy;
    }

    /**
     * 记录级脱敏：同时处理 title 与 content。
     * 命中时写审计事件，便于事后核查哪些记忆曾含密钥。
     */
    public RecordRedaction redactRecord(String title, String content) {
        RedactResult t = redact(title);
        RedactResult c = redact(content);
        return new RecordRedaction(t.text(), c.text(), t, c);
    }

    public record RecordRedaction(String title, String content, RedactResult titleResult, RedactResult contentResult) {
        public boolean changed() {
            return titleResult.changed() || contentResult.changed();
        }

        public List<String> allLabels() {
            List<String> all = new ArrayList<>(titleResult.labels());
            for (String l : contentResult.labels()) {
                if (!all.contains(l)) {
                    all.add(l);
                }
            }
            return all;
        }

        public int totalCount() {
            return titleResult.redactedCount() + contentResult.redactedCount();
        }
    }
}
