# ODR-023 — Escopo de InstrumentationFunction e a relação Instrument / MeasurementInstrument

**Status:** Aberto — decisão pendente
**Data:** 2026-08-14
**Levantado em:** revisão do Bloco 1 do ODR-022 §19
**Afeta:** `copi-vocab` (COPI_0000029), `copi-core` (COPI_0000024, congelada), 27 entradas de
enriquecimento, e o guard `check_tsensor_subclass_mesinstr.sparql`

---

## O problema

O raciocinador infere hoje:

```
Instrument (COPI_0000091)  ⊑  MeasurementInstrument (COPI_0000024)
```

Ou seja, **todo instrumento é um instrumento de medição**. A leitura intuitiva é a inversa: um
instrumento de medição deveria ser um *tipo* de instrumento.

`MeasurementInstrument` é a única categoria da `copi-core` com subclasse inferida, e é por
`Instrument` que as 15 entradas de medição (manômetro, densitômetro, medidor de vazão…) herdam a
classificação. Não é detalhe periférico: é o caminho pelo qual uma das 9 categorias de equipamento
do paper é povoada.

## De onde vem

`InstrumentationFunction` (COPI_0000029, `copi-vocab`) carrega uma restrição universal:

```turtle
copi:COPI_0000029 a owl:Class ;
    rdfs:subClassOf iof-constr:DesignedFunction ,
        [ owl:onProperty obo:BFO_0000054 ; owl:someValuesFrom iof-constr:MeasurementProcess ] ,
        [ owl:onProperty obo:BFO_0000054 ; owl:allValuesFrom  iof-constr:MeasurementProcess ] .
```

O `allValuesFrom` afirma que **todo** processo que realiza uma função de instrumentação é um
processo de medição. Como

```
Instrument ≡ MaterialArtifact ⊓ ∃hasFunction.InstrumentationFunction
MeasurementInstrument ≡ MaterialArtifact ⊓ ∃hasFunction.(DesignedFunction ⊓ ∃realizedIn.MeasurementProcess)
```

o instrumento herda a restrição e fica **mais estreito** que a categoria — daí a inversão.

## O que as normas dizem

**ISA 5.1** — `instrument`:

> "a device used for direct or indirect measurement, monitoring, **and/or control** of a variable,
> including primary elements, indicators, **controllers**, **final control elements**, computing
> devices, and electrical devices such as annunciators, **switches**, and **pushbuttons**."

Controlador, elemento final de controle (válvula de controle), chave e botoeira **não medem**.
Pela ISA, `instrument` é claramente mais amplo que medição.

**ISO 15926** — `MEASURING INSTRUMENT`:

> "an INSTRUMENTATION FUNCTION that handles the measurement result from an internal or external
> MEASURING ELEMENT"

Distingue quem **trata o resultado** (instrumento) de quem **sente** (elemento) — e trata
"instrumentation" como o gênero, "measuring" como o recorte.

**A própria COPI** — a definição em linguagem natural da entrada `instrument` diz "measurement,
monitoring, **or control** of process variables", contradizendo o próprio axioma. E a definição
NL da COPI_0000029 diz "a função de detectar e converter uma grandeza física em um sinal ou
leitura utilizável" — isso é **sensoreamento**, não instrumentação no sentido da ISA. A classe
está **nomeada como o gênero amplo e axiomatizada como a espécie estreita**.

## As duas leituras

**(A) O axioma está errado.** `InstrumentationFunction` deveria perder o `allValuesFrom`, ou ser
renomeada para o que de fato descreve (`SensingFunction`), com uma função de instrumentação
genuinamente ampla acima dela. `Instrument` volta a ser o gênero e `MeasurementInstrument` o
recorte de medição.

**(B) O nome está errado.** O paper pode querer `MeasurementInstrument` como a categoria ampla de
"equipamento que produz informação em vez de matéria" — e nesse caso o problema é a entrada
`Instrument`, que ao ser definida pela função de sensoreamento deveria chamar-se outra coisa.

As duas são defensáveis. A escolha depende da intenção do paper, não da evidência das normas.

## O que trava

1. **`copi-core` está congelada.** `COPI_0000024` é uma das 9 categorias de equipamento do paper
   FOMI/FOIS. Mexer em quem classifica sob ela mexe no que o paper afirma.
2. **27 entradas** usam `InstrumentationFunction` como função ou `Instrument` como genus.
3. **Existe guard ativo:** `scripts/sparql/check_tsensor_subclass_mesinstr.sparql` exige
   `TemperatureSensor ⊑ MeasurementInstrument` (modo `--nivel1`). Relaxar o `allValuesFrom`
   provavelmente o quebra — e esse guard pode estar codificando exatamente a intenção do paper,
   o que seria evidência a favor da leitura (B).

## O que não trava

A revisão do Bloco 1 seguiu sem esta decisão. `measuring element` foi colocado sob `Instrument`
com `axiom_mode='necessary'`, o que é correto nas **duas** leituras: o elemento é
inequivocamente da família de medição, então herdar de `Instrument` é seguro independentemente de
como a relação `Instrument`/`MeasurementInstrument` venha a ser resolvida.

## Próximo passo

Decidir entre (A) e (B) à luz do que o paper afirma sobre as 9 categorias. Se (A), planejar a
mudança junto com o guard do `--nivel1` e as 27 entradas dependentes.
