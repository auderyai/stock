BEGIN_FUNCTION_MAP
	.Func,�ֽ�íƮ(���ֿ���)(t8451),t8451,attr,block,headtype=A;
	BEGIN_DATA_MAP
	t8451InBlock,�⺻�Է�,input;
	begin
		�����ڵ�,shcode,shcode,char,6;
		�ֱⱸ��(2:��3:��4:��5:��),gubun,gubun,char,1;
		��û�Ǽ�(�ִ�-����:2000�����:500),qrycnt,qrycnt,long,4;
		��������,sdate,sdate,char,8;
		��������,edate,edate,char,8;
		��������,cts_date,cts_date,char,8;
		���࿩��(Y:����N:�����),comp_yn,comp_yn,char,1;
		�����ְ�����(Y:����N:������),sujung,sujung,char,1;
		�ŷ��ұ����ڵ�,exchgubun,exchgubun,char,1;
	end
	t8451OutBlock,���,output;
	begin
		�����ڵ�,shcode,shcode,char,6;
		���Ͻð�,jisiga,jisiga,long,8;
		���ϰ���,jihigh,jihigh,long,8;
		��������,jilow,jilow,long,8;
		��������,jiclose,jiclose,long,8;
		���ϰŷ���,jivolume,jivolume,long,12;
		���Ͻð�,disiga,disiga,long,8;
		���ϰ���,dihigh,dihigh,long,8;
		��������,dilow,dilow,long,8;
		��������,diclose,diclose,long,8;
		���Ѱ�,highend,highend,long,8;
		���Ѱ�,lowend,lowend,long,8;
		��������,cts_date,cts_date,char,8;
		����۽ð�(HHMMSS),s_time,s_time,char,6;
		������ð�(HHMMSS),e_time,e_time,char,6;
		����ȣ��ó���ð�(MM:��),dshmin,dshmin,char,2;
		���ڵ�ī��Ʈ,rec_count,rec_count,long,7;
		����VI���Ѱ�,svi_uplmtprice,svi_uplmtprice,long,8;
		����VI���Ѱ�,svi_dnlmtprice,svi_dnlmtprice,long,8;
        NXT������������۽ð�(HHMMSS)         , nxt_fm_s_time, nxt_fm_s_time, char      , 6;
        NXT��������������ð�(HHMMSS)         , nxt_fm_e_time, nxt_fm_e_time, char      , 6;
        NXT�������ϵ���ȣ��ó���ð�(MM:��)    , nxt_fm_dshmin, nxt_fm_dshmin, char      , 2;
        NXT�����͸�������۽ð�(HHMMSS)       , nxt_am_s_time, nxt_am_s_time, char      , 6;
        NXT�����͸���������ð�(HHMMSS)       , nxt_am_e_time, nxt_am_e_time, char      , 6;
        NXT�����͸��ϵ���ȣ��ó���ð�(MM:��)  , nxt_am_dshmin, nxt_am_dshmin, char      , 2;
        KRX������������۽ð�(HHMMSS)         , krx_fm_s_time, krx_fm_s_time, char      , 6;
        KRX��������������ð�(HHMMSS)         , krx_fm_e_time, krx_fm_e_time, char      , 6;
        KRX�������ϵ���ȣ��ó���ð�(MM:��)    , krx_fm_dshmin, krx_fm_dshmin, char      , 2;
        KRX�����͸�������۽ð�(HHMMSS)       , krx_am_s_time, krx_am_s_time, char      , 6;
        KRX�����͸���������ð�(HHMMSS)       , krx_am_e_time, krx_am_e_time, char      , 6;
        KRX�����͸��ϵ���ȣ��ó���ð�(MM:��)  , krx_am_dshmin, krx_am_dshmin, char      , 2;
	end
	t8451OutBlock1,���1,output,occurs;
	begin
		��¥,date,date,char,8;
		�ð�,open,open,long,12;
		����,high,high,long,12;
		����,low,low,long,12;
		����,close,close,long,12;
		�ŷ���,jdiff_vol,jdiff_vol,long,12;
		�ŷ����,value,value,long,12;
		��������,jongchk,jongchk,long,13;
		��������,rate,rate,double,6.2;
		�����ְ��ݿ��׸�,pricechk,pricechk,long,13;
		���������ݿ��ŷ����,ratevalue,ratevalue,long,12;
		�����������(1:����2:���3:����4:����5:�϶��ֽ��ϸ����),sign,sign,char,1;
	end
	END_DATA_MAP
END_FUNCTION_MAP
