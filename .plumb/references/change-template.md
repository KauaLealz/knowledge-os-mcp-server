# Change Template

Use este template para todas as mudanças no repositório (trilhas padrão e profunda).

```markdown
# [Título da Mudança]

**Status:** Aguardando aprovação / Em progresso / Concluída

**Trilha:** [direta / padrão / profunda]

**ID:** [ticket ou slug]

## Objetivo

Uma frase: o que será construído.

## Critérios de Aceite

- [ ] AC1: ...
- [ ] AC2: ...

## Fora de Escopo

O que explicitamente NÃO será feito.

## Tasks

### T1: [Descrição]
- [ ] [Sub-item]
- [ ] [Sub-item]
**Comando de verificação:** `...`

### T2: [Descrição]
...

## Decisões de Design

### [Decisão 1]
Opções consideradas, a escolhida, por quê.

## Riscos

| Risco | Mitigação |
|---|---|
| ... | ... |

## Notas

Contexto importante que não cabe em Decisões.

## Retro

- `regra`: ...
- `padrão novo`: arquivo-que-virou-modelo.ext
- `lacuna`: descrição da capacidade que faltou

---

**Branch:** feature/...
**Base:** main
```
