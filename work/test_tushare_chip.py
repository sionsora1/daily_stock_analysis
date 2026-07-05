from data_provider.tushare_fetcher import TushareFetcher
f = TushareFetcher()
chip = f.get_chip_distribution('603259')
print('RESULT', type(chip).__name__ if chip else 'NONE')
if chip:
    print('DATE', chip.date)
    print('PROFIT', chip.profit_ratio)
    print('AVG', chip.avg_cost)
    print('C90', chip.concentration_90)
